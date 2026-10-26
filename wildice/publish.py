"""Build and write the status JSON the map reads."""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

from wildice.models import Confidence, Label, Lake, Score

DISCLAIMER = "Rough estimate only — check ice yourself."


def display_name(lake: Lake) -> str:
    return lake.name or f"Unnamed lake ({lake.area_acres:.0f} ac)"


def browser_url(lat: float, lon: float, day: date | None) -> str:
    url = (f"https://browser.dataspace.copernicus.eu/?zoom=14&lat={lat}&lng={lon}"
           "&themeId=DEFAULT-THEME&datasetId=S2_L2A_CDAS&layerId=1_TRUE_COLOR")
    if day is not None:
        url += (f"&dateMode=SINGLE&fromTime={day.isoformat()}T00:00:00.000Z"
                f"&toTime={day.isoformat()}T23:59:59.999Z")
    return url


def build_status(lakes: list[Lake], scores: dict[str, Score], pinned: frozenset[str],
                 hidden: frozenset[str], history: dict[str, list[dict]], run_date: date,
                 stale_since: date | None) -> dict:
    out: dict[str, dict] = {}
    for lake in lakes:
        sc = scores.get(lake.id)
        label = sc.label if sc else Label.UNKNOWN
        out[lake.id] = {
            "name": display_name(lake),
            "label": str(label),
            "confidence": str(sc.confidence if sc else Confidence.LOW),
            "reason": sc.reason if sc else "no data",
            "thickness_cm": sc.thickness_cm if sc else None,
            "last_clear_day": sc.last_clear_day.isoformat() if sc and sc.last_clear_day else None,
            "browser_url": browser_url(lake.lat, lake.lon, sc.last_clear_day if sc else None),
            "thumb": f"thumbs/{lake.id}.png",
            "pinned": lake.id in pinned,
            "hidden": lake.id in hidden,
            "warning": lake.warning,
            "history": list(history.get(lake.id, [])),
        }
    return {
        "run_date": run_date.isoformat(),
        "stale_since": stale_since.isoformat() if stale_since else None,
        "disclaimer": DISCLAIMER,
        "lakes": out,
    }


def load_history(history_dir: Path, run_date: date, days: int = 14) -> dict[str, list[dict]]:
    history_dir = Path(history_dir)
    result: dict[str, list[dict]] = {}
    if not history_dir.is_dir():
        return result
    start = run_date - timedelta(days=days - 1)
    files = []
    for f in history_dir.glob("*.json"):
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if start <= d <= run_date:
            files.append((d, f))
    for d, f in sorted(files):
        try:
            labels = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for lake_id, label in labels.items():
            result.setdefault(lake_id, []).append({"day": d.isoformat(), "label": label})
    return result


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_outputs(status: dict, site_data: Path, run_date: date) -> None:
    site_data = Path(site_data)
    out = copy.deepcopy(status)
    for lake_id, entry in out["lakes"].items():
        entry["thumb"] = (f"thumbs/{lake_id}.png"
                          if (site_data / "thumbs" / f"{lake_id}.png").exists() else None)
    _write_json(site_data / "status.json", out)
    _write_json(site_data / "history" / f"{run_date.isoformat()}.json",
                {k: v["label"] for k, v in out["lakes"].items()})
