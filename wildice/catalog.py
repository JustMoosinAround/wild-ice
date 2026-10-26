"""Build the watched-lake catalog from OpenStreetMap (Overpass)."""
from __future__ import annotations

import json
import math
import os
import shutil
import time
from pathlib import Path
from typing import Literal

import osm2geojson
import requests
from shapely.geometry import mapping, shape

from wildice.config import Config, load_config
from wildice.geo import LineIndex, area_acres, interior
from wildice.models import Lake

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Overpass's usage policy asks clients to identify themselves; it answers the
# anonymous default "python-requests" User-Agent with 406 Not Acceptable.
USER_AGENT = "wildice/0.1 (personal lake-ice skating tool)"
TIMEOUT_S = 180
RETRIES = 3
TILE_DEG = 0.5  # half-degree tiles keep each Overpass query light
PAUSE_S = 3  # courtesy pause between Overpass requests
BACKOFF_S = (30, 60, 120)  # waits before each retry of an overloaded/failed query
CACHE_DIR = Path(".cache/overpass")  # per-tile results, so a failed build resumes
NARROW_WARNING = "Lake too narrow for satellite readings"
# A 200 response whose "remark" mentions one of these is a failed query.
ERROR_REMARKS = ("error", "timeout", "out of memory")

Bbox = tuple[float, float, float, float]  # south, west, north, east

_ROADS = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|service"


def tiles(bbox: Bbox, step: float = TILE_DEG) -> list[Bbox]:
    south, west, north, east = bbox
    out: list[Bbox] = []
    n_lat = max(1, math.ceil(round((north - south) / step, 9)))
    n_lon = max(1, math.ceil(round((east - west) / step, 9)))
    for i in range(n_lat):
        s = south + i * step
        n = min(north, s + step)
        for j in range(n_lon):
            w = west + j * step
            e = min(east, w + step)
            out.append((round(s, 6), round(w, 6), round(n, 6), round(e, 6)))
    return out


def overpass_query(kind: Literal["water", "roads", "trails"], bbox: Bbox) -> str:
    b = "({},{},{},{})".format(*bbox)
    if kind == "water":
        sel = []
        for el in ("way", "relation"):
            sel.append(f'{el}["natural"="water"]["water"~"^(lake|pond|reservoir)$"]{b};')
            sel.append(f'{el}["natural"="water"][!"water"]{b};')
    elif kind == "roads":
        sel = [f'way["highway"~"^({_ROADS})(_link)?$"]{b};']
    elif kind == "trails":
        sel = [f'way["highway"~"^(path|track|footway|bridleway)$"]{b};',
               f'way["snowmobile"~"^(yes|designated)$"]{b};']
    else:
        raise ValueError(f"unknown kind: {kind}")
    return f"[out:json][timeout:{TIMEOUT_S}];\n(\n  " + "\n  ".join(sel) + "\n);\nout geom;"


def _post(session: requests.Session, query: str) -> dict:
    for attempt in range(RETRIES + 1):
        last = attempt == RETRIES
        try:
            resp = session.post(OVERPASS_URL, data={"data": query}, timeout=TIMEOUT_S,
                                headers={"User-Agent": USER_AGENT})
        except (requests.ConnectionError, requests.Timeout):
            if last:
                raise
            time.sleep(BACKOFF_S[attempt])
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and not last:
            time.sleep(BACKOFF_S[attempt])
            continue
        resp.raise_for_status()
        data = resp.json()
        remark = str(data.get("remark") or "") if isinstance(data, dict) else ""
        if any(word in remark.lower() for word in ERROR_REMARKS):
            if last:
                raise requests.HTTPError(f"Overpass query failed: {remark}", response=resp)
            time.sleep(BACKOFF_S[attempt])
            continue
        return data
    raise AssertionError("unreachable")


def _tile_path(cache_dir: Path, kind: str, tile: Bbox) -> Path:
    return cache_dir / ("{}_{}_{}_{}_{}.json".format(kind, *tile))


def _save_tile(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def fetch_osm(kind: Literal["water", "roads", "trails"], bbox: Bbox,
              session: requests.Session, cache_dir: Path | None = None) -> list[dict]:
    """GeoJSON features for every tile, deduplicated by OSM type+id.

    With cache_dir, each tile's raw Overpass result is saved as it arrives and
    reused on the next call, so a build that fails part-way resumes.
    """
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    requested = False
    for tile in tiles(bbox):
        path = _tile_path(cache_dir, kind, tile) if cache_dir is not None else None
        if path is not None and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            if requested:
                time.sleep(PAUSE_S)
            requested = True
            data = _post(session, overpass_query(kind, tile))
            if path is not None:
                _save_tile(path, data)
        for feat in osm2geojson.json2geojson(data)["features"]:
            props = feat["properties"]
            key = (props["type"], props["id"])
            if key not in seen:
                seen.add(key)
                out.append(feat)
    return out


def _lake_id(feat: dict) -> str:
    p = feat["properties"]
    return ("r" if p["type"] == "relation" else "w") + str(p["id"])


def _line_geoms(feats: list[dict]) -> list:
    geoms = []
    for f in feats:
        g = shape(f["geometry"])
        if g.geom_type in ("Polygon", "MultiPolygon"):
            g = g.boundary
        if not g.is_empty:
            geoms.append(g)
    return geoms


def _plain(geom) -> dict:
    return json.loads(json.dumps(mapping(geom)))


def build_catalog(water: list[dict], roads: list[dict], trails: list[dict],
                  cfg: Config) -> list[Lake]:
    road_idx = LineIndex(_line_geoms(roads))
    trail_idx = LineIndex(_line_geoms(trails))
    f = cfg.filters
    pinned = set(cfg.pinned)
    lakes: list[Lake] = []
    for feat in water:
        geom = shape(feat["geometry"])
        if geom.geom_type not in ("Polygon", "MultiPolygon") or geom.is_empty:
            continue
        lake_id = _lake_id(feat)
        is_pinned = lake_id in pinned
        acres = area_acres(geom)
        if acres < f.min_area_acres and not is_pinned:
            continue
        road = road_idx.nearest_miles(geom)
        trail = trail_idx.nearest_miles(geom)
        near = (road is not None and road <= f.max_road_miles) or \
               (trail is not None and trail <= f.max_trail_miles)
        if not near and not is_pinned:
            continue
        inner = interior(geom, cfg.imagery.shore_buffer_m)
        if inner is None and not is_pinned:
            continue
        pt = geom.representative_point()
        lakes.append(Lake(
            id=lake_id,
            name=(feat["properties"].get("tags") or {}).get("name"),
            area_acres=acres,
            road_mi=road,
            trail_mi=trail,
            lat=pt.y,
            lon=pt.x,
            interior=_plain(inner) if inner is not None else None,
            warning=NARROW_WARNING if inner is None else None,
        ))
    return lakes


def write_catalog(lakes: list[Lake], path: Path) -> None:
    features = []
    for lake in lakes:
        props = {k: v for k, v in lake.__dict__.items() if k != "interior"}
        features.append({"type": "Feature", "geometry": lake.interior, "properties": props})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}),
                    encoding="utf-8", newline="\n")


def load_catalog(path: Path) -> list[Lake]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Lake(interior=f["geometry"], **f["properties"]) for f in data["features"]]


def main() -> None:
    cfg = load_config(Path("config.yaml"))
    session = requests.Session()
    bbox = cfg.region.bbox
    water = fetch_osm("water", bbox, session, CACHE_DIR)
    roads = fetch_osm("roads", bbox, session, CACHE_DIR)
    trails = fetch_osm("trails", bbox, session, CACHE_DIR)
    lakes = build_catalog(water, roads, trails, cfg)
    write_catalog(lakes, Path("site/data/lakes.geojson"))
    shutil.rmtree(CACHE_DIR, ignore_errors=True)  # next build fetches fresh data
    print(f"wrote {len(lakes)} lakes")


if __name__ == "__main__":
    main()
