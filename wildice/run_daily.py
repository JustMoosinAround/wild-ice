"""Once-a-day job: weather -> ice model -> imagery -> scores -> site data + alert."""
from __future__ import annotations

from dataclasses import replace

import argparse
import calendar
import json
import logging
import os
import sys
import time
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from wildice import alert, publish
from wildice.catalog import load_catalog
from wildice.config import Config, load_config
from wildice.icemodel import run_ice_model
from wildice.imagery import Budget, CopernicusClient, fetch_imagery, s1_baseline
from wildice.models import (
    ImageryStats, Label, Lake, S1Obs, Score, SourceUnavailable, SurfaceClass,
)
from wildice.prefs import load_prefs
from wildice.hazards import ridge_note
from wildice.reports import apply_report, ice_with_report, load_reports
from wildice.scenes import Seen, load_seen, new_sensors, save_seen
from wildice.score import optical_classes, score_lake, valid_ls_classes, valid_s2_classes
from wildice.shortlist import shortlist
from wildice.weather import cell_of, cell_points, make_session, season_start, update_cache

log = logging.getLogger(__name__)

TIMEZONE = "America/Anchorage"
OPS_TITLE = "Wild ice job failed"
OPS_MARKER_ENV = "WILDICE_OPS_MARKER"  # file written after a successful ops push
THUMB_LABELS = (Label.LIKELY_BLACK_ICE, Label.FREEZING)
REQUESTS_PER_LAKE = 3  # at most one S2 + one S1 + one Landsat statistics request
_clock = time.monotonic  # replaced in tests
FATAL_CLIENT_STATUS = frozenset({401, 403, 429})  # auth / rate limit: stop the run


def days_left_in_month(run_date: date) -> int:
    """Days remaining in run_date's month, today included."""
    return calendar.monthrange(run_date.year, run_date.month)[1] - run_date.day + 1


def ntfy_session() -> requests.Session:
    """Plain session: no urllib3 retries, so a 5xx after delivery can't double-push."""
    return requests.Session()


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _ping_ops(env: Mapping[str, str], body: str, session: requests.Session) -> None:
    topic = env.get("NTFY_TOPIC_OPS")
    if not topic:
        log.warning("ops topic not configured; not sending failure push")
        return
    try:
        alert.send_ntfy(topic, OPS_TITLE, body, None, session)
    except SourceUnavailable as exc:  # message never contains the topic
        log.error("ops push failed: %s", exc)
        return
    marker = env.get(OPS_MARKER_ENV)
    if marker:  # tells the workflow's fallback curl step ops already knows
        try:
            Path(marker).write_text("1\n", encoding="utf-8")
        except OSError as exc:
            log.warning("could not write ops marker: %s", type(exc).__name__)


def _write_stale(site_data: Path, run_date: date) -> None:
    """Keep the previous lakes; mark the page stale since the last good run."""
    prev = _read_json(site_data / "status.json")
    if isinstance(prev, dict) and isinstance(prev.get("lakes"), dict):
        since = prev.get("stale_since") or prev.get("run_date") or run_date.isoformat()
        status = {**prev, "run_date": run_date.isoformat(), "stale_since": since}
    else:
        status = publish.build_status([], {}, frozenset(), frozenset(), {}, run_date,
                                      stale_since=run_date)
    _write_json(site_data / "status.json", status)


S2History = dict[str, dict[date, SurfaceClass]]  # also used for Landsat classes


def _load_s2_history(path: Path, start: date) -> S2History:
    """Per-lake valid camera classes this season; malformed or pre-season entries dropped."""
    raw = _read_json(path)
    out: S2History = {}
    if not isinstance(raw, dict):
        return out
    for lake_id, days in raw.items():
        if not isinstance(days, dict):
            continue
        kept: dict[date, SurfaceClass] = {}
        for day, cls in days.items():
            try:
                d, c = date.fromisoformat(str(day)), SurfaceClass(cls)
            except ValueError:
                continue
            if d >= start:
                kept[d] = c
        if kept:
            out[str(lake_id)] = kept
    return out


def _save_s2_history(path: Path, history: S2History) -> None:
    _write_json(path, {lake_id: {d.isoformat(): str(days[d]) for d in sorted(days)}
                       for lake_id, days in sorted(history.items()) if days})


S1History = dict[str, dict[date, float]]


def _load_s1_history(path: Path, start: date) -> S1History:
    """Per-lake radar readings (VV dB) this season, kept for days with no new pass."""
    raw = _read_json(path)
    out: S1History = {}
    if not isinstance(raw, dict):
        return out
    for lake_id, days in raw.items():
        if not isinstance(days, dict):
            continue
        kept: dict[date, float] = {}
        for day, db in days.items():
            try:
                d, v = date.fromisoformat(str(day)), float(db)
            except (TypeError, ValueError):
                continue
            if d >= start:
                kept[d] = v
        if kept:
            out[str(lake_id)] = kept
    return out


def _save_s1_history(path: Path, history: S1History) -> None:
    _write_json(path, {lake_id: {d.isoformat(): days[d] for d in sorted(days)}
                       for lake_id, days in sorted(history.items()) if days})


def _is_login_failure(exc: SourceUnavailable) -> bool:
    return exc.status in FATAL_CLIENT_STATUS or "token:" in str(exc)


def _load_last_checked(path: Path, start: date) -> dict[str, date]:
    """When each lake last got a satellite request this season."""
    raw = _read_json(path)
    out: dict[str, date] = {}
    if isinstance(raw, dict):
        for lake_id, day in raw.items():
            try:
                d = date.fromisoformat(str(day))
            except ValueError:
                continue
            if d >= start:
                out[str(lake_id)] = d
    return out


def _save_last_checked(path: Path, checked: dict[str, date]) -> None:
    _write_json(path, {k: checked[k].isoformat() for k in sorted(checked)})


def _make_client(env: Mapping[str, str], session: requests.Session,
                 budget: Budget) -> CopernicusClient | None:
    cid, secret = env.get("CDSE_CLIENT_ID"), env.get("CDSE_CLIENT_SECRET")
    if not cid or not secret:
        log.warning("Copernicus credentials not set; labels from weather only")
        return None
    return CopernicusClient(cid, secret, session, budget=budget)


def _new_scenes(client, lake_list: list[Lake], seen: Seen, run_date: date, cfg: Config,
                env: Mapping[str, str], ntfy: requests.Session) -> Seen:
    """Lakes under a scene newer than their last request; {} if the catalog is down."""
    start = run_date - timedelta(days=cfg.imagery.lookback_days)
    try:
        scenes = client.scenes(cfg.region.bbox, start, run_date)
    except SourceUnavailable as exc:
        if _is_login_failure(exc):
            raise
        log.error("scene catalog failed: %s; satellite skipped today", exc)
        _ping_ops(env, "copernicus catalog unavailable; weather-only labels today", ntfy)
        return {}
    wanted = new_sensors(lake_list, scenes, seen)
    log.info("scene catalog: %d scenes, %d lakes with something new", len(scenes),
             len(wanted))
    return wanted


def _pick(ranked: list[str], wanted: Seen, allowance: int) -> list[str]:
    """Best-ranked lakes with a new scene, until today's request allowance is used."""
    ids: list[str] = []
    cost = 0
    for lake_id in ranked:
        if lake_id not in wanted:
            continue
        n = len(wanted[lake_id])
        if cost + n > allowance:
            break
        ids.append(lake_id)
        cost += n
    return ids


def _with_saved_radar(img: ImageryStats | None, saved: dict[date, float],
                      window_start: date, run_date: date, ice, lake_id: str,
                      baselines: dict) -> ImageryStats | None:
    """Today's numbers, plus radar readings from earlier passes still in the window."""
    s1 = {o.day: o for o in (img.s1 if img else ())}
    for day, db in saved.items():
        if window_start <= day <= run_date and day not in s1:
            s1[day] = S1Obs(day, db)
    if img is None and not s1:
        return None
    key = f"{lake_id}:{ice.freeze_up.isoformat()}" if ice.freeze_up else None
    baseline = img.s1_baseline_db if img else (baselines.get(key) if key else None)
    return ImageryStats(s2=img.s2 if img else (),
                        s1=tuple(s1[d] for d in sorted(s1)),
                        s1_baseline_db=baseline)


def _imagery(client, lakes: dict[str, Lake], ids: list[str], ice0: dict, run_date: date,
             cfg: Config, budget: Budget, baselines: dict,
             checked: dict[str, date], wanted: Seen, seen: Seen) -> dict[str, ImageryStats]:
    """Request numbers for `ids`, asking each lake only for the sensors in `wanted`."""
    out: dict[str, ImageryStats] = {}
    limit_s = cfg.imagery.max_minutes_per_run * 60
    started = _clock()
    for done, lake_id in enumerate(ids):
        if _clock() - started > limit_s:
            # Stop so the run can save and publish; unchecked lakes go first tomorrow.
            log.info("imagery time limit reached; %d shortlisted lakes left for tomorrow",
                     len(ids) - done)
            break
        lake = lakes[lake_id]
        freeze_up = ice0[lake_id].freeze_up
        sensors = set(wanted[lake_id])
        key = f"{lake_id}:{freeze_up.isoformat()}" if freeze_up else None
        need_baseline = "s1" in sensors and key is not None and key not in baselines
        if budget.remaining() < len(sensors) + int(need_baseline):
            log.info("request budget exhausted; %d shortlisted lakes skipped",
                     len(ids) - done)
            break
        checked[lake_id] = run_date  # attempted, even if a lake-specific error follows
        # Attempted counts as seen: a lake that errors waits for the next new scene.
        seen.setdefault(lake_id, {}).update(wanted[lake_id])
        t0 = _clock()
        try:
            if need_baseline:
                baselines[key] = s1_baseline(client, lake, freeze_up)
            out[lake_id] = fetch_imagery(client, lake, run_date, cfg,
                                         baselines.get(key) if key else None, sensors)
        except SourceUnavailable as exc:
            if not _lake_specific(exc):
                raise
            log.warning("imagery for %s skipped: HTTP %s", lake_id, exc.status)
        log.info("imagery for %s took %.0f s (%.0f acres)", lake_id, _clock() - t0,
                 lake.area_acres)
    if ids:
        log.info("imaged %d lakes in %.1f min", len(checked_today(checked, run_date)),
                 (_clock() - started) / 60)
    return out


def checked_today(checked: dict[str, date], run_date: date) -> list[str]:
    return [k for k, v in checked.items() if v == run_date]


def _lake_specific(exc: SourceUnavailable) -> bool:
    """A 4xx about this lake's request (bad geometry etc.), not auth or rate limiting."""
    return (exc.status is not None and 400 <= exc.status < 500
            and exc.status not in FATAL_CLIENT_STATUS)


def _thumbnails(client, lakes: dict[str, Lake], scores: dict[str, Score], prev: dict | None,
                thumbs_dir: Path, budget: Budget) -> None:
    prev_lakes = prev.get("lakes", {}) if isinstance(prev, dict) else {}
    for lake_id, sc in scores.items():
        lake = lakes[lake_id]
        if sc.label not in THUMB_LABELS or sc.last_clear_day is None or lake.interior is None:
            continue
        path = thumbs_dir / f"{lake_id}.png"
        prev_day = (prev_lakes.get(lake_id) or {}).get("last_clear_day")
        if prev_day == sc.last_clear_day.isoformat() and path.exists():
            continue
        if budget.remaining() < 1:
            log.info("request budget exhausted; skipping thumbnails")
            return
        try:
            png = client.truecolor_png(lake.interior, sc.last_clear_day, sc.last_clear_sensor)
        except SourceUnavailable as exc:  # cosmetic: keep the run going
            log.warning("thumbnail for %s failed: %s", lake_id, exc)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)


def _run(run_date: date, root: Path, env: Mapping[str, str], session: requests.Session,
         client, ntfy: requests.Session) -> int:
    root = Path(root)
    site_data = root / "site" / "data"
    state = root / "state"
    cfg = load_config(root / "config.yaml")
    lake_list = load_catalog(site_data / "lakes.geojson")
    lakes = {lake.id: lake for lake in lake_list}
    pinned, hidden = load_prefs(cfg, root / "prefs")
    reports = load_reports(root / "ratings", run_date, season_start(run_date, cfg))
    budget = Budget(state / "usage.json", cfg.imagery.monthly_request_budget,
                    today=lambda: run_date)
    baselines_path = state / "baselines.json"
    baselines = _read_json(baselines_path)
    baselines = baselines if isinstance(baselines, dict) else {}
    prev_status = _read_json(site_data / "status.json")
    s2_history_path = state / "s2_history.json"
    s2_history = _load_s2_history(s2_history_path, season_start(run_date, cfg))
    ls_history_path = state / "ls_history.json"
    ls_history = _load_s2_history(ls_history_path, season_start(run_date, cfg))
    last_checked_path = state / "last_checked.json"
    last_checked = _load_last_checked(last_checked_path, season_start(run_date, cfg))
    seen_path = state / "seen_scenes.json"
    seen = load_seen(seen_path, season_start(run_date, cfg))
    s1_history_path = state / "s1_history.json"
    s1_history = _load_s1_history(s1_history_path, season_start(run_date, cfg))

    try:
        wx = update_cache(state / "weather", cell_points(lake_list), run_date, cfg, session)
        # earlier clearings this season count before today's imagery is in
        traces: dict[str, list] = {lake.id: [] for lake in lake_list}
        ice0 = {lake.id: ice_with_report(wx[cell_of(lake.lat, lake.lon)], cfg,
                                         optical_classes(s2_history.get(lake.id),
                                                         ls_history.get(lake.id)),
                                         lake.area_acres,
                                         reports.get(lake.id), traces[lake.id])
                for lake in lake_list}

        if client is None:
            client = _make_client(env, session, budget)
        # spread what is left of the monthly budget evenly over the rest of the month
        allowance = min(budget.remaining() // days_left_in_month(run_date),
                        cfg.imagery.max_lakes_per_day * REQUESTS_PER_LAKE)
        ranked = (shortlist(lake_list, ice0, pinned, cfg,
                            remaining_requests=REQUESTS_PER_LAKE * len(lake_list),
                            hidden=hidden, last_checked=last_checked)
                  if client is not None and allowance > 0 else [])
        # no lake worth a request today: don't spend one on the catalog either
        wanted = (_new_scenes(client, lake_list, seen, run_date, cfg, env, ntfy)
                  if ranked else {})
        ids = _pick(ranked, wanted, allowance)
        imagery = _imagery(client, lakes, ids, ice0, run_date, cfg, budget, baselines,
                           last_checked, wanted, seen)
        _save_last_checked(last_checked_path, last_checked)
        save_seen(seen_path, seen)
        for lake_id, img in imagery.items():
            for obs in img.s1:
                s1_history.setdefault(lake_id, {})[obs.day] = obs.vv_db
        _save_s1_history(s1_history_path, s1_history)
        for lake_id, img in imagery.items():
            today = valid_s2_classes(img, cfg)
            if today:
                s2_history[lake_id] = {**s2_history.get(lake_id, {}), **today}
        _save_s2_history(s2_history_path, s2_history)
        for lake_id, img in imagery.items():
            today = valid_ls_classes(img, cfg)
            if today:
                ls_history[lake_id] = {**ls_history.get(lake_id, {}), **today}
        _save_s2_history(ls_history_path, ls_history)

        scores: dict[str, Score] = {}
        window_start = run_date - timedelta(days=cfg.imagery.lookback_days)
        for lake in lake_list:
            hist = optical_classes(s2_history.get(lake.id), ls_history.get(lake.id))
            rep = reports.get(lake.id)
            ice = (ice_with_report(wx[cell_of(lake.lat, lake.lon)], cfg, hist, lake.area_acres,
                                   rep)
                   if lake.id in imagery else ice0[lake.id])
            img = _with_saved_radar(imagery.get(lake.id), s1_history.get(lake.id, {}),
                                    window_start, run_date, ice, lake.id, baselines)
            sc = score_lake(lake, ice, img, run_date, cfg, s2_history=s2_history.get(lake.id),
                            ls_history=ls_history.get(lake.id))
            sc = apply_report(sc, rep, ice, hist, run_date, cfg)
            ridges = ridge_note(lake, wx[cell_of(lake.lat, lake.lon)], ice, run_date, cfg)
            scores[lake.id] = replace(sc, reason=f"{sc.reason}; {ridges}") if ridges else sc

        if client is not None:
            _thumbnails(client, lakes, scores, prev_status, site_data / "thumbs", budget)
    except SourceUnavailable as exc:
        # The detail names the source and the error (status, URL, OAuth reason); it never
        # contains secrets: credentials travel in request bodies, and ntfy errors are
        # reduced to type and status before they get here.
        log.error("data source failed: %s", exc)
        _write_stale(site_data, run_date)
        _ping_ops(env, f"{exc.source} unavailable", ntfy)
        return 1
    finally:
        log.info("imagery requests used %d/%d this month", budget.used, budget.limit)
        budget.save()
        _write_json(baselines_path, baselines)

    # Load before writing, and drop today's entry, so a same-day rerun matches the first run.
    history = {k: [h for h in v if h["day"] != run_date.isoformat()]
               for k, v in publish.load_history(site_data / "history", run_date).items()}
    status = publish.build_status(lake_list, scores, pinned, hidden, history, run_date,
                                  stale_since=None)
    publish.write_outputs(status, site_data, run_date)
    publish.write_series(site_data, {
        lake.id: publish.lake_series(wx[cell_of(lake.lat, lake.lon)], traces[lake.id])
        for lake in lake_list})
    log.info("wrote status for %d lakes (%d with imagery)", len(scores), len(imagery))

    labels_path = state / "labels.json"
    new = alert.newly_black_ice(scores, alert.load_labels(labels_path), lakes, pinned, hidden)
    if new:
        topic = env.get("NTFY_TOPIC_ALERTS")
        if not topic:
            log.error("alerts topic not configured; %d alert(s) not sent", len(new))
            _ping_ops(env, "alerts topic not configured", ntfy)
            return 1  # labels not saved: the alert goes out once the secret is set
        title, body, click = alert.format_alert(new, lakes, scores, pinned, cfg.site.base_url)
        try:
            alert.send_ntfy(topic, title, body, click, ntfy)
        except SourceUnavailable as exc:
            log.error("alert push failed: %s", exc)
            _ping_ops(env, f"{exc.source} unavailable", ntfy)
            return 1  # labels not saved: tomorrow's run retries the alert
        log.info("alert sent for %d lake(s)", len(new))
    alert.save_labels(labels_path, scores)
    return 0


def run(run_date: date, root: Path, env: Mapping[str, str], session: requests.Session,
        client: CopernicusClient | None = None) -> int:
    """Run the daily job; return the process exit code.

    `session` carries weather (and Copernicus, when the client is built here) traffic;
    ntfy pushes always go through a non-retrying session (see `ntfy_session`).
    """
    ntfy = ntfy_session()
    try:
        return _run(run_date, root, env, session, client, ntfy)
    except Exception as exc:
        try:  # keep the map honest: the last good labels, marked stale
            _write_stale(Path(root) / "site" / "data", run_date)
        except Exception as stale_exc:  # never mask the original failure
            log.error("could not write stale status: %s", type(stale_exc).__name__)
        _ping_ops(env, type(exc).__name__, ntfy)
        raise


def today_local() -> date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m wildice.run_daily")
    parser.add_argument("--date", type=date.fromisoformat, default=None,
                        help="run date YYYY-MM-DD (default: today in America/Anchorage)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run_date = args.date or today_local()
    return run(run_date, Path.cwd(), os.environ, make_session())


if __name__ == "__main__":
    sys.exit(main())
