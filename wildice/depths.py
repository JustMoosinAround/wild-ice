"""Mean lake depths from HydroLAKES (see data/README.md), matched to catalog lakes."""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path

import shapely
from shapely import STRtree
from shapely.geometry import shape

from wildice.geo import _project, _TO_AK
from wildice.models import Lake

DEPTHS_CSV = Path(__file__).resolve().parent.parent / "data" / "hydrolakes_southcentral.csv"
_ACRES_PER_KM2 = 247.105
SHORE_M = 300          # outlet points sit on or just off the shoreline
MAX_AREA_RATIO = 3.0   # HydroLAKES and OpenStreetMap outlines differ; beyond this, a different lake


@dataclass(frozen=True)
class DepthPoint:
    hylak_id: int
    name: str
    area_km2: float
    depth_avg_m: float
    lon: float
    lat: float


def load_points(path: Path = DEPTHS_CSV) -> list[DepthPoint]:
    with open(path, newline="", encoding="utf-8") as f:
        return [DepthPoint(int(r["hylak_id"]), r["lake_name"], float(r["area_km2"]),
                           float(r["depth_avg_m"]), float(r["pour_lon"]), float(r["pour_lat"]))
                for r in csv.DictReader(f)]


def attach_depths(lakes: list[Lake], points: list[DepthPoint]) -> list[Lake]:
    """Lakes with depth_m set where a HydroLAKES outlet of similar area sits on the shore."""
    shaped = [(i, _project(shape(l.interior)).buffer(SHORE_M))
              for i, l in enumerate(lakes) if l.interior is not None]
    if not shaped:
        return list(lakes)
    tree = STRtree([g for _, g in shaped])
    xs, ys = _TO_AK.transform([p.lon for p in points], [p.lat for p in points])
    best: dict[int, tuple[float, float]] = {}  # lake index -> (area mismatch, depth)
    for p, x, y in zip(points, xs, ys):
        pt = shapely.Point(x, y)
        for j in tree.query(pt):
            i, geom = shaped[j]
            if not geom.contains(pt):
                continue
            mismatch = abs(math.log(p.area_km2 * _ACRES_PER_KM2 / lakes[i].area_acres))
            if mismatch <= math.log(MAX_AREA_RATIO) and (i not in best or mismatch < best[i][0]):
                best[i] = (mismatch, p.depth_avg_m)
    return [replace(l, depth_m=best[i][1]) if i in best else l for i, l in enumerate(lakes)]
