"""Build the watched-lake catalog from OpenStreetMap (Overpass)."""
from __future__ import annotations

import json
import math
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
TIMEOUT_S = 180
RETRIES = 3
NARROW_WARNING = "Lake too narrow for satellite readings"

Bbox = tuple[float, float, float, float]  # south, west, north, east

_ROADS = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|service"


def tiles(bbox: Bbox, step: float = 1.0) -> list[Bbox]:
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
            resp = session.post(OVERPASS_URL, data={"data": query}, timeout=TIMEOUT_S)
        except (requests.ConnectionError, requests.Timeout):
            if last:
                raise
            time.sleep(2 ** attempt * 5)
            continue
        if resp.status_code in (429, 500, 502, 503, 504) and not last:
            time.sleep(2 ** attempt * 5)
            continue
        resp.raise_for_status()
        return resp.json()
    raise AssertionError("unreachable")


def fetch_osm(kind: Literal["water", "roads", "trails"], bbox: Bbox,
              session: requests.Session) -> list[dict]:
    """GeoJSON features for every tile, deduplicated by OSM type+id."""
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    for tile in tiles(bbox):
        data = _post(session, overpass_query(kind, tile))
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
    water = fetch_osm("water", bbox, session)
    roads = fetch_osm("roads", bbox, session)
    trails = fetch_osm("trails", bbox, session)
    lakes = build_catalog(water, roads, trails, cfg)
    write_catalog(lakes, Path("site/data/lakes.geojson"))
    print(f"wrote {len(lakes)} lakes")


if __name__ == "__main__":
    main()
