"""Calibrate the crack-line detector (wildice/cracks.py) on known days. Walled off.

    CDSE_CLIENT_ID=... CDSE_CLIENT_SECRET=... python -m reference.cracks.calibrate

For each case, finds the clearest Sentinel-2 look in the window, fetches it at
~10 m (capped at MAX_PX on the long side) and prints the share of the lake covered
by thin bright lines and the background brightness between them.
"""
from __future__ import annotations

import math
import os
import sys
from datetime import date
from pathlib import Path

from shapely.geometry import shape

from wildice.catalog import load_catalog
from wildice.config import load_config
from wildice.cracks import crack_stats
from wildice.imagery import CopernicusClient
from wildice.score import classify_s2
from wildice.weather import make_session

MAX_PX = 2000
RES_M = 10.0

# (lake_id, first day, last day, what people saw)
CASES = [
    # skated
    ("r1555333", "2025-02-12", "2025-02-12", "skated (owner, Feb 8-9)"),
    ("r1555333", "2025-02-20", "2025-02-20", "skated (Reddit Feb 15)"),
    ("r1555333", "2024-01-19", "2024-01-24", "skated (Reddit Jan 25-26)"),
    ("r21378422", "2024-01-19", "2024-01-22", "skated (Reddit Jan 18)"),
    ("w49200373", "2025-01-08", "2025-01-08", "skated (Reddit Jan 1-4)"),
    ("w284700420", "2025-11-09", "2025-11-12", "skated (Reddit Nov 14)"),
    ("w217233544", "2025-12-14", "2025-12-17", "skated (Reddit Dec 14)"),
    ("r1568485", "2024-11-19", "2024-11-21", "skated (Reddit Nov 21)"),
    ("w351056287", "2025-12-14", "2025-12-14", "skated (Reddit Dec 14)"),
    ("r1569302", "2025-12-14", "2025-12-17", "skated (Reddit Dec 16)"),
    ("r2375186", "2025-11-09", "2025-11-09", "skateable (Reddit Nov 11)"),
    # snow covered
    ("r1555333", "2024-01-27", "2024-02-01", "snow"),
    ("w218458735", "2025-11-09", "2025-11-12", "snow"),
    ("w351056287", "2025-12-17", "2025-12-17", "snow"),
    ("r1527882", "2026-03-01", "2026-03-15", "snow (mostly)"),
    # open water (fall, before freeze-up)
    ("r1555333", "2025-10-01", "2025-10-25", "open"),
    ("w49200373", "2025-10-01", "2025-10-25", "open"),
    ("r1527882", "2025-10-01", "2025-10-25", "open"),
    ("r21378422", "2025-10-01", "2025-10-25", "open"),
]


def _size(geometry: dict) -> tuple[int, int]:
    minx, miny, maxx, maxy = shape(geometry).bounds
    lat = math.radians((miny + maxy) / 2)
    w_m = (maxx - minx) * 111_320 * math.cos(lat)
    h_m = (maxy - miny) * 110_540
    scale = max(1.0, max(w_m, h_m) / RES_M / MAX_PX)
    return max(32, round(w_m / RES_M / scale)), max(32, round(h_m / RES_M / scale))


def main() -> int:
    root = Path(__file__).resolve().parent.parent.parent
    cfg = load_config(root / "config.yaml")
    lakes = {l.id: l for l in load_catalog(root / "site" / "data" / "lakes.geojson")}
    client = CopernicusClient(os.environ["CDSE_CLIENT_ID"], os.environ["CDSE_CLIENT_SECRET"],
                              make_session())
    print(f"{'lake':<24} {'day':<10} {'class':<6} {'bright':>6} {'lines':>6} {'bg':>5} {'m/px':>5}  truth")
    for lake_id, a, b, truth in CASES:
        lake = lakes[lake_id]
        try:
            obs = [o for o in client.s2_stats(lake.interior, date.fromisoformat(a), date.fromisoformat(b))
                   if classify_s2(o, cfg) is not None]
            if not obs:
                print(f"{lake.name:<24} {a:<10} no clear look  {truth}")
                continue
            o = max(obs, key=lambda o: o.valid_fraction)
            w, h = _size(lake.interior)
            st = crack_stats(client.truecolor_png(lake.interior, o.day, "s2", w, h))
            minx, miny, maxx, maxy = shape(lake.interior).bounds
            mpp = (maxx - minx) * 111_320 * math.cos(math.radians(miny)) / w
            bright = (o.b03 + o.b04) / 2
            print(f"{lake.name[:24]:<24} {o.day!s:<10} {classify_s2(o, cfg).value:<6} {bright:6.3f} "
                  f"{(st.line_frac if st else float('nan')):6.3f} {(st.background if st else float('nan')):5.2f} "
                  f"{mpp:5.0f}  {truth}")
        except Exception as exc:  # report and keep going
            print(f"{lake.name:<24} {a:<10} ERROR {exc}  {truth}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
