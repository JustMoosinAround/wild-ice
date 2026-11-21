"""The daily job's view of the Ice Log: reports, pin/hide prefs and the review count,
fetched from the Cloudflare worker (worker/) with a service token.

Friends' reports never touch the public repo. A friend's report whose photo or phone
location is too far from the chosen lake is dropped as "wrong lake"; one without any
location is kept and flagged. The owner's reports are always trusted.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

import requests
import shapely
from shapely.geometry import shape

from wildice.config import Config
from wildice.geo import _project, _TO_AK
from wildice.models import Lake
from wildice.reports import GRADES, RATINGS, Report

log = logging.getLogger(__name__)

TIMEOUT_S = 30


@dataclass(frozen=True)
class Export:
    reports: list[dict]
    prefs: list[dict]
    pending_comments: int
    pending_photos: int


def fetch_export(base_url: str, token: str, since: date,
                 session: requests.Session) -> Export | None:
    """Everything the daily run needs from the worker; None (and a log line) on any
    failure, so a worker outage never stops the run. The token is never logged."""
    try:
        r = session.get(f"{base_url.rstrip('/')}/api/export", params={"since": since.isoformat()},
                        headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        pending = data["pending"]
        return Export(list(data["reports"]), list(data["prefs"]),
                      int(pending["comments"]), int(pending["photos"]))
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        log.error("ice log unavailable: HTTP %s", status)
    except requests.RequestException as exc:
        log.error("ice log unavailable: %s", type(exc).__name__)
    except (ValueError, KeyError, TypeError) as exc:
        log.error("ice log: unexpected response (%s)", type(exc).__name__)
    return None


def _distance_m(lake: Lake, lat: float, lon: float) -> float:
    x, y = _TO_AK.transform(lon, lat)
    return _project(shape(lake.interior)).distance(shapely.Point(x, y))


def reports_from_export(rows: Iterable[Mapping], lakes: Mapping[str, Lake], run_date: date,
                        season_start: date, cfg: Config) -> dict[str, Report]:
    """Newest usable report per lake, with how many usable reports it had this week."""
    kept: dict[str, list[tuple[date, str, Report]]] = defaultdict(list)
    for row in rows:
        try:
            lake = lakes.get(str(row["lake_id"]))
            day = date.fromisoformat(str(row["day"]))
            rating, grade = row["rating"], row.get("grade")
        except (KeyError, TypeError, ValueError):
            continue
        if lake is None or rating not in RATINGS or (grade is not None and grade not in GRADES):
            continue
        if not season_start <= day <= run_date:
            continue
        source = "owner" if row.get("role") == "owner" else "friend"
        verified = "ok"
        lat, lon = row.get("lat"), row.get("lon")
        if source == "friend":
            if lat is None or lon is None:
                verified = "no_gps"
            elif lake.interior is not None and _distance_m(lake, lat, lon) > cfg.icelog.max_gps_m:
                continue  # wrong lake
        report = Report(day, rating, str(row.get("note") or ""), grade=grade, source=source,
                        verified=verified)
        kept[lake.id].append((day, str(row.get("created_at") or ""), report))
    out: dict[str, Report] = {}
    week_start = run_date - timedelta(days=6)
    for lake_id, items in kept.items():
        items.sort(key=lambda t: (t[0], t[1]))
        week = sum(1 for d, _, _ in items if d >= week_start)
        newest = items[-1][2]
        out[lake_id] = Report(newest.day, newest.rating, newest.note, grade=newest.grade,
                              source=newest.source, verified=newest.verified,
                              week_count=max(1, week))
    return out


def merge_reports(repo: Mapping[str, Report], icelog: Mapping[str, Report]) -> dict[str, Report]:
    """Repo reports (owner, before the Ice Log) and Ice Log reports: later day wins,
    the Ice Log on a tie."""
    out = dict(repo)
    for lake_id, rep in icelog.items():
        old = out.get(lake_id)
        if old is None or rep.day >= old.day:
            out[lake_id] = rep
    return out
