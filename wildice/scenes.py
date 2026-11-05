"""Which lakes a new Sentinel scene has covered since their last satellite request.

Sentinel-2 and Landsat 8-9 photograph a given lake every few days and Sentinel-1
radar passes less often, so asking for every lake's numbers every day mostly re-reads images
already seen. The daily run asks the image catalog what arrived, then requests
numbers only for lakes under a scene newer than the one they last got.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from shapely import STRtree
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from wildice.models import Lake

SENSORS = ("s2", "s1", "ls")  # Sentinel-2 photo, Sentinel-1 radar, Landsat 8-9 photo

# lake id -> sensor -> acquisition time of the newest scene already requested
Seen = dict[str, dict[str, datetime]]


@dataclass(frozen=True)
class Scene:
    sensor: str            # "s2", "s1" or "ls"
    time: datetime         # acquisition time, UTC
    footprint: BaseGeometry


def new_sensors(lakes: Iterable[Lake], scenes: list[Scene], seen: Seen) -> Seen:
    """Per lake, each sensor with a covering scene newer than `seen`, and its newest time."""
    if not scenes:
        return {}
    tree = STRtree([s.footprint for s in scenes])
    out: Seen = {}
    for lake in lakes:
        if lake.interior is None:
            continue
        newest: dict[str, datetime] = {}
        for i in tree.query(shape(lake.interior), predicate="intersects"):
            sc = scenes[int(i)]
            if sc.sensor not in newest or sc.time > newest[sc.sensor]:
                newest[sc.sensor] = sc.time
        before = seen.get(lake.id, {})
        fresh = {s: t for s, t in newest.items() if s not in before or t > before[s]}
        if fresh:
            out[lake.id] = fresh
    return out


def load_seen(path: Path, start: date) -> Seen:
    """Saved newest-scene times; this season only, junk entries dropped."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: Seen = {}
    if not isinstance(raw, dict):
        return out
    for lake_id, by_sensor in raw.items():
        if not isinstance(by_sensor, dict):
            continue
        kept: dict[str, datetime] = {}
        for sensor, when in by_sensor.items():
            try:
                t = datetime.fromisoformat(str(when))
            except ValueError:
                continue
            if sensor in SENSORS and t.date() >= start:
                kept[sensor] = t
        if kept:
            out[str(lake_id)] = kept
    return out


def save_seen(path: Path, seen: Seen) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: {s: seen[k][s].isoformat() for s in sorted(seen[k])}
            for k in sorted(seen) if seen[k]}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
