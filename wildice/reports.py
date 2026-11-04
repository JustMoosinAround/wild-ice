"""Your on-the-ice reports ("How was it?") feeding back into the daily labels.

The map saves each report to ratings/<day>-<ms>-<lake>.json. The newest report per
lake this season wins:
  water   the ice estimate restarts from zero after the report day
  skated  shown as likely black ice until snow covers it
  snow    shown as snow covered until a satellite image sees dark ice again
  rough   label unchanged, note shown
Reports older than REPORT_DAYS stop changing the label (an open-water report keeps
its effect through the restarted ice estimate).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from wildice.config import Config
from wildice.icemodel import TraceRow, run_ice_model
from wildice.models import Confidence, DayWeather, IceState, Label, Score, SurfaceClass

log = logging.getLogger(__name__)

RATINGS = ("skated", "snow", "water", "rough")
REPORT_DAYS = 7
_PHRASE = {"skated": "skateable ice", "snow": "snow on the ice", "water": "open water",
           "rough": "rough ice"}


@dataclass(frozen=True)
class Report:
    day: date
    rating: str
    note: str


def load_reports(ratings_dir: Path, run_date: date, season_start: date) -> dict[str, Report]:
    """Newest valid report per lake from this season, up to run_date."""
    ratings_dir = Path(ratings_dir)
    out: dict[str, Report] = {}
    if not ratings_dir.is_dir():
        return out
    for f in sorted(ratings_dir.glob("*.json"), key=lambda p: p.name):
        try:
            item = json.loads(f.read_text(encoding="utf-8"))
            lake_id, rating = str(item["lake_id"]), str(item["rating"])
            day = date.fromisoformat(str(item["day"]))
        except (ValueError, KeyError, TypeError) as e:
            log.warning("skipping malformed report %s: %r", f.name, e)
            continue
        if rating not in RATINGS:
            log.warning("skipping report %s: unknown rating %r", f.name, rating)
            continue
        if not season_start <= day <= run_date:
            continue
        prev = out.get(lake_id)
        if prev is None or day >= prev.day:
            out[lake_id] = Report(day, rating, str(item.get("note") or "")[:200])
    return out


def ice_with_report(days: Sequence[DayWeather], cfg: Config,
                    s2_classes: Mapping[date, SurfaceClass] | None, area_acres: float | None,
                    report: Report | None, trace: list[TraceRow] | None = None) -> IceState:
    """Ice model, restarted from open water (at 0 C) after an open-water report."""
    if report is None or report.rating != "water":
        return run_ice_model(days, cfg, s2_classes, area_acres, trace)
    before = [d for d in days if d.day < report.day]
    after = [d for d in days if d.day > report.day]
    if trace is not None:
        run_ice_model(before, cfg, s2_classes, area_acres, trace)  # what the model thought
        if any(d.day == report.day for d in days):
            trace.append((report.day, 0.0, 0.0))
    later = {k: v for k, v in (s2_classes or {}).items() if k > report.day}
    return run_ice_model(after, cfg, later, None, trace)


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"


def apply_report(score: Score, report: Report | None, ice: IceState,
                 s2_classes: Mapping[date, SurfaceClass], run_date: date, cfg: Config) -> Score:
    if report is None or (run_date - report.day).days > REPORT_DAYS:
        return score
    label, conf = score.label, score.confidence
    if report.rating == "skated":
        snowed = (ice.last_snow_day is not None and ice.last_snow_day > report.day
                  and ice.snow_since_reset_cm > cfg.snow.cover_cm)
        if not snowed:
            label, conf = Label.LIKELY_BLACK_ICE, Confidence.HIGH
    elif report.rating == "snow":
        cleared = any(d > report.day and c is SurfaceClass.DARK for d, c in s2_classes.items())
        if not cleared:
            label, conf = Label.SNOW_COVERED, Confidence.HIGH
    elif report.rating == "water" and label is Label.OPEN_WATER:
        conf = Confidence.HIGH
    note = f' ("{report.note}")' if report.note else ""
    reason = f"You reported {_PHRASE[report.rating]} on {_fmt(report.day)}{note}; {score.reason}"
    return replace(score, label=label, confidence=conf, reason=reason)
