"""Per-lake fields for the app's Explore feed and lake page (status.json).

came_in: the first day of the lake's current run of "in" (skateable) labels.
timeline: what we know about the lake and when, newest first. No names or notes:
status.json is public.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from wildice.models import ResetEvent, ResetKind, SurfaceClass

IN_LABELS = ("likely_black_ice", "rough_ice")

_REPORT = {"skated": "Skated", "rough": "Skated, rough", "snow": "Snow on the ice reported",
           "water": "Open water reported"}
_IMAGE = {SurfaceClass.CRACKED: "Crack network seen", SurfaceClass.DARK: "Dark on image",
          SurfaceClass.WHITE: "White (snow) on image", SurfaceClass.GREY: "Grey on image",
          SurfaceClass.WATER: "Open water on image"}
_RESET = {ResetKind.FREEZE_UP: "Froze up", ResetKind.LIKELY: "Thaw or rain, then refroze",
          ResetKind.CONFIRMED: "Fresh surface confirmed"}
_ORDER = {"report": 0, "image": 1, "snow": 2, "reset": 3}


def came_in(history: Sequence[Mapping], label: str, run_date: date) -> date | None:
    """First day of the current in-run, counting today. A single non-in day between
    in-days doesn't end the run; two in a row do."""
    if label not in IN_LABELS:
        return None
    start, gap = run_date, 0
    for row in sorted(history, key=lambda r: r["day"], reverse=True):
        day = date.fromisoformat(row["day"])
        if day >= run_date:
            continue
        if row["label"] in IN_LABELS:
            start, gap = day, 0
        else:
            gap += 1
            if gap >= 2:
                break
    return start


def timeline(report, classes: Mapping[date, SurfaceClass],
             snow: tuple[date, float, str] | None, reset: ResetEvent | None,
             limit: int = 8) -> list[dict]:
    events: list[tuple[date, str, str]] = []
    if report is not None:
        text = _REPORT.get(report.rating, "Reported")
        if report.grade and report.rating in ("skated", "rough"):
            text += f" ({report.grade})"
        events.append((report.day, "report", text))
    for day, cls in classes.items():
        if cls in _IMAGE:
            events.append((day, "image", _IMAGE[cls]))
    if snow is not None:
        events.append((snow[0], "snow", f"{snow[1]:.0f} cm new snow at {snow[2]}"))
    image_days = set(classes)
    if reset is not None and not (reset.kind is ResetKind.CONFIRMED and reset.day in image_days):
        events.append((reset.day, "reset", _RESET.get(reset.kind, "Reset")))
    events.sort(key=lambda e: (-e[0].toordinal(), _ORDER[e[1]]))
    return [{"day": d.isoformat(), "kind": k, "text": t} for d, k, t in events[:limit]]


_HAZARD = {"new_ice": "New ice", "slush": "Slush", "lead": "Lead risk", "ridge": "Pressure ridges",
           "big_ice": "Big ice"}


def hazards(notes) -> list[dict]:
    """Short labels for the lake page's hazard chips, each with its full note.
    `notes` is [(kind, text or None)] in the order the daily run makes them."""
    out = []
    for kind, text in notes:
        if not text:
            continue
        if kind == "thaw":
            label = "Rotten ice risk" if text.startswith("rotten") else "Thaw-weakened"
        else:
            label = _HAZARD.get(kind)
        if label:
            out.append({"label": label, "text": text[0].upper() + text[1:]})
    return out
