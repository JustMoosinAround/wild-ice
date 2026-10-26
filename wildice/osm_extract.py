"""Lakes, roads and trails from the Geofabrik Alaska OpenStreetMap extract.

The extract is downloaded once (about 140 MB) and read locally with pyosmium.
Features come out in the same GeoJSON shape the catalog builder expects:
properties {"type": "way"|"relation", "id": int, "tags": {...}}.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import osmium
import requests
from shapely import wkb
from shapely.geometry import box
from shapely.prepared import prep

EXTRACT_URL = "https://download.geofabrik.de/north-america/us/alaska-latest.osm.pbf"
USER_AGENT = "wildice/0.1 (personal lake-ice skating tool)"
MAX_AGE_S = 7 * 24 * 3600  # reuse a downloaded extract for up to a week
TIMEOUT_S = 120

Bbox = tuple[float, float, float, float]  # south, west, north, east

_LAKE_WATER = {"lake", "pond", "reservoir"}
_ROAD = re.compile(r"^(motorway|trunk|primary|secondary|tertiary|unclassified"
                   r"|residential|service)(_link)?$")
_TRAIL = re.compile(r"^(path|track|footway|bridleway)$")
_SNOWMOBILE = {"yes", "designated"}


def download_extract(path: Path, session: requests.Session) -> Path:
    """Download the Alaska extract to path unless a copy under a week old is there."""
    if path.exists() and time.time() - path.stat().st_mtime < MAX_AGE_S:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    try:
        with session.get(EXTRACT_URL, stream=True, timeout=TIMEOUT_S,
                         headers={"User-Agent": USER_AGENT}) as resp:
            resp.raise_for_status()
            with open(part, "wb") as out:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    out.write(chunk)
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
    return path


def _is_lake(tags) -> bool:
    return tags.get("natural") == "water" and tags.get("water", "lake") in _LAKE_WATER


def _is_road(tags) -> bool:
    return bool(_ROAD.match(tags.get("highway", "")))


def _is_trail(tags) -> bool:
    return bool(_TRAIL.match(tags.get("highway", ""))) or tags.get("snowmobile") in _SNOWMOBILE


def _feature(kind: str, osm_id: int, tags, geom) -> dict:
    return {"type": "Feature",
            "properties": {"type": kind, "id": osm_id, "tags": dict(tags)},
            "geometry": json.loads(json.dumps(geom.__geo_interface__))}


def read_layers(pbf_path: Path, bbox: Bbox) -> tuple[list[dict], list[dict], list[dict]]:
    """(water, roads, trails) features that touch bbox, read from an OSM file."""
    south, west, north, east = bbox
    region = prep(box(west, south, east, north))
    factory = osmium.geom.WKBFactory()
    water: list[dict] = []
    roads: list[dict] = []
    trails: list[dict] = []
    processor = (osmium.FileProcessor(str(pbf_path))
                 .with_locations()
                 .with_areas(osmium.filter.TagFilter(("natural", "water"))))
    for obj in processor:
        if obj.is_area():
            if not _is_lake(obj.tags):
                continue
            try:
                geom = wkb.loads(factory.create_multipolygon(obj), hex=True)
            except (RuntimeError, osmium.InvalidLocationError):
                continue  # broken multipolygon in the source data
            if region.intersects(geom):
                kind = "way" if obj.from_way() else "relation"
                water.append(_feature(kind, obj.orig_id(), obj.tags, geom))
        elif obj.is_way():
            tags = obj.tags
            road, trail = _is_road(tags), _is_trail(tags)
            if not (road or trail) or len(obj.nodes) < 2:
                continue
            try:
                geom = wkb.loads(factory.create_linestring(obj), hex=True)
            except (RuntimeError, osmium.InvalidLocationError):
                continue
            if not region.intersects(geom):
                continue
            feat = _feature("way", obj.id, tags, geom)
            if road:
                roads.append(feat)
            if trail:
                trails.append(feat)
    return water, roads, trails
