"""Once-a-day job: weather -> ice model -> imagery -> scores -> site data + alert."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from wildice import alert, publish
from wildice.catalog import load_catalog
from wildice.config import Config, load_config
from wildice.icemodel import run_ice_model
from wildice.imagery import Budget, CopernicusClient, fetch_imagery, s1_baseline
from wildice.models import ImageryStats, Label, Lake, Score, SourceUnavailable
from wildice.prefs import load_prefs
from wildice.score import score_lake, valid_s2_classes
from wildice.shortlist import shortlist
from wildice.weather import cell_of, make_session, update_cache

log = logging.getLogger(__name__)

TIMEZONE = "America/Anchorage"
OPS_TITLE = "Wild ice job failed"
THUMB_LABELS = (Label.LIKELY_BLACK_ICE, Label.FREEZING)
REQUESTS_PER_LAKE = 2  # one S2 + one S1 statistics request


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


def _make_client(env: Mapping[str, str], session: requests.Session,
                 budget: Budget) -> CopernicusClient | None:
    cid, secret = env.get("CDSE_CLIENT_ID"), env.get("CDSE_CLIENT_SECRET")
    if not cid or not secret:
        log.warning("Copernicus credentials not set; labels from weather only")
        return None
    return CopernicusClient(cid, secret, session, budget=budget)


def _imagery(client, lakes: dict[str, Lake], ids: list[str], ice0: dict, run_date: date,
             cfg: Config, budget: Budget, baselines: dict) -> dict[str, ImageryStats]:
    out: dict[str, ImageryStats] = {}
    for lake_id in ids:
        lake = lakes[lake_id]
        freeze_up = ice0[lake_id].freeze_up
        key = f"{lake_id}:{freeze_up.isoformat()}" if freeze_up else None
        need_baseline = key is not None and key not in baselines
        if budget.remaining() < REQUESTS_PER_LAKE + int(need_baseline):
            log.info("request budget exhausted; %d shortlisted lakes skipped",
                     len(ids) - len(out))
            break
        if need_baseline:
            baselines[key] = s1_baseline(client, lake, freeze_up)
        out[lake_id] = fetch_imagery(client, lake, run_date, cfg,
                                     baselines.get(key) if key else None)
    return out


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
            png = client.truecolor_png(lake.interior, sc.last_clear_day)
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
    budget = Budget(state / "usage.json", cfg.imagery.monthly_request_budget,
                    today=lambda: run_date)
    baselines_path = state / "baselines.json"
    baselines = _read_json(baselines_path)
    baselines = baselines if isinstance(baselines, dict) else {}
    prev_status = _read_json(site_data / "status.json")

    try:
        cells = sorted({cell_of(lake.lat, lake.lon) for lake in lake_list})
        wx = update_cache(state / "weather", cells, run_date, cfg, session)
        ice0 = {lake.id: run_ice_model(wx[cell_of(lake.lat, lake.lon)], cfg)
                for lake in lake_list}

        if client is None:
            client = _make_client(env, session, budget)
        ids = (shortlist(lake_list, ice0, pinned, cfg, remaining_requests=budget.remaining())
               if client is not None else [])
        imagery = _imagery(client, lakes, ids, ice0, run_date, cfg, budget, baselines)

        scores: dict[str, Score] = {}
        for lake in lake_list:
            img = imagery.get(lake.id)
            ice = (run_ice_model(wx[cell_of(lake.lat, lake.lon)], cfg,
                                 valid_s2_classes(img, cfg))
                   if img is not None else ice0[lake.id])
            scores[lake.id] = score_lake(lake, ice, img, run_date, cfg)

        if client is not None:
            _thumbnails(client, lakes, scores, prev_status, site_data / "thumbs", budget)
    except SourceUnavailable as exc:
        log.error("data source failed: %s", exc.source)
        _write_stale(site_data, run_date)
        _ping_ops(env, f"{exc.source} unavailable", ntfy)
        return 1
    finally:
        budget.save()
        _write_json(baselines_path, baselines)

    # Load before writing, and drop today's entry, so a same-day rerun matches the first run.
    history = {k: [h for h in v if h["day"] != run_date.isoformat()]
               for k, v in publish.load_history(site_data / "history", run_date).items()}
    status = publish.build_status(lake_list, scores, pinned, hidden, history, run_date,
                                  stale_since=None)
    publish.write_outputs(status, site_data, run_date)
    log.info("wrote status for %d lakes (%d with imagery)", len(scores), len(imagery))

    labels_path = state / "labels.json"
    new = alert.newly_black_ice(scores, alert.load_labels(labels_path), lakes, pinned, hidden)
    if new:
        topic = env.get("NTFY_TOPIC_ALERTS")
        if not topic:
            log.warning("alerts topic not configured; %d alert(s) not sent", len(new))
        else:
            title, body, click = alert.format_alert(new, lakes, scores, pinned,
                                                    cfg.site.base_url)
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
