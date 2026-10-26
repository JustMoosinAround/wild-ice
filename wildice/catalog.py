"""Build the watched-lake catalog from the OpenStreetMap Alaska extract."""
from __future__ import annotations

import json
from pathlib import Path

import requests
from shapely.geometry import mapping, shape

from wildice.config import Config, load_config
from wildice.geo import LineIndex, area_acres, interior
from wildice.models import Lake
from wildice.osm_extract import download_extract, read_layers

NARROW_WARNING = "Lake too narrow for satellite readings"
EXTRACT_PATH = Path(".cache/osm/alaska-latest.osm.pbf")


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
    pbf = download_extract(EXTRACT_PATH, requests.Session())
    water, roads, trails = read_layers(pbf, cfg.region.bbox)
    lakes = build_catalog(water, roads, trails, cfg)
    write_catalog(lakes, Path("site/data/lakes.geojson"))
    print(f"wrote {len(lakes)} lakes")


if __name__ == "__main__":
    main()
