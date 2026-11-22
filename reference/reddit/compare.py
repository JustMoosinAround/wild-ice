"""Satellite looks around skating days reported on r/nordicskating (walled off).

    CDSE_CLIENT_ID=... CDSE_CLIENT_SECRET=... python -m reference.reddit.compare

Reads reference/reddit/observations.yaml, asks Copernicus for clear Sentinel-2 and
Landsat looks within a week of each day (the same check as the Strava skating
reference) and writes reference/reddit/REPORT.md. Nothing in the daily run reads
this folder; delete it to roll back.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import yaml

from wildice.catalog import load_catalog
from wildice.config import load_config
from wildice.imagery import CopernicusClient
from wildice.models import SourceUnavailable
from wildice.publish import browser_url
from wildice.skatelog import Trip, nearby_looks
from wildice.weather import make_session

HERE = Path(__file__).resolve().parent


def main() -> int:
    root = HERE.parent.parent
    cfg = load_config(root / "config.yaml")
    lakes = {l.id: l for l in load_catalog(root / "site" / "data" / "lakes.geojson")}
    doc = yaml.safe_load((HERE / "observations.yaml").read_text(encoding="utf-8"))
    client = CopernicusClient(os.environ["CDSE_CLIENT_ID"], os.environ["CDSE_CLIENT_SECRET"],
                              make_session())
    lines = ["# r/nordicskating reports vs. satellite (walled off)", "",
             "Clear Sentinel-2 / Landsat looks within 7 days of each reported day. "
             "Not used by the daily run.", "",
             "| Day | Lake | Day stated? | Clear looks | Post |", "|---|---|---|---|---|"]
    for o in doc["observations"]:
        lake, day = lakes[o["lake_id"]], date.fromisoformat(str(o["day"]))
        try:
            looks = nearby_looks(client, Trip(day, lake, "Reddit", 0, 0, ""), cfg)
            cell = "<br>".join(
                f"[{lk.day}]({browser_url(lake.lat, lake.lon, lk.day, lk.sensor)}) "
                + ("Landsat " if lk.sensor == "ls" else "")
                + f"{lk.cls.value} (bright {lk.brightness:.3f}, NDSI {lk.ndsi:.2f})"
                for lk in looks) or "none (cloudy or no imagery)"
        except SourceUnavailable as exc:
            cell = f"error: {exc}"
        print(day, lake.name, cell.replace("<br>", " | ")[:300])
        lines.append(f"| {day} | {lake.name} ({lake.id}) | {'yes' if o.get('day_stated') else 'post date'} "
                     f"| {cell} | [link]({o['url']}) |")
    (HERE / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
