import json
from dataclasses import replace
from pathlib import Path

import osm2geojson
import pytest

from wildice.catalog import build_catalog, load_catalog, write_catalog
from wildice.config import load_config

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def cfg():
    return load_config(Path(__file__).parent.parent / "config.yaml")


def _feats(kind):
    return osm2geojson.json2geojson(json.loads((FIX / f"overpass_{kind}.json").read_text()))["features"]


@pytest.fixture
def layers():
    return _feats("water"), _feats("roads"), _feats("trails")


def test_filters(layers, cfg):
    assert {l.id for l in build_catalog(*layers, cfg)} == {"w1001", "w1002"}


def test_distances_and_fields(layers, cfg):
    by_id = {l.id: l for l in build_catalog(*layers, cfg)}
    a, b = by_id["w1001"], by_id["w1002"]
    assert a.road_mi == pytest.approx(1.5, rel=0.05)
    assert b.road_mi == pytest.approx(3.0, rel=0.05)
    assert b.trail_mi == pytest.approx(0.5, rel=0.1)
    assert a.area_acres == pytest.approx(40, rel=0.1)
    assert a.interior["type"] in ("Polygon", "MultiPolygon")
    assert a.warning is None
    assert 61.0 < b.lat < 61.01 and -148.92 < b.lon < -148.90


def test_pinned_bypasses(layers, cfg):
    got = {l.id for l in build_catalog(*layers, replace(cfg, pinned=("w1003",)))}
    assert got == {"w1001", "w1002", "w1003"}


def test_pinned_small_lake_included(layers, cfg):
    got = {l.id for l in build_catalog(*layers, replace(cfg, pinned=("w1004",)))}
    assert "w1004" in got


def test_unnamed_name_none(layers, cfg):
    by_id = {l.id: l for l in build_catalog(*layers, cfg)}
    assert by_id["w1001"].name is None
    assert by_id["w1002"].name == "Bravo Lake"


def test_narrow_lake_dropped_unless_pinned(cfg):
    # ~40 m wide, 800 m long, right beside the road
    ring = [(61.0, -148.9990), (61.0, -148.9983), (61.0072, -148.9983), (61.0072, -148.9990), (61.0, -148.9990)]
    geom = {"type": "Polygon", "coordinates": [[[lon, lat] for lat, lon in ring]]}
    narrow = {"type": "Feature", "geometry": geom,
              "properties": {"type": "way", "id": 9, "tags": {"natural": "water"}}}
    roads = _feats("roads")
    assert build_catalog([narrow], roads, [], cfg) == []
    got = build_catalog([narrow], roads, [], replace(cfg, pinned=("w9",)))
    assert len(got) == 1
    assert got[0].interior is None
    assert got[0].warning == "Lake too narrow for satellite readings"


def test_relation_id_prefix(cfg):
    ring = [[-148.99, 61.0], [-148.98, 61.0], [-148.98, 61.01], [-148.99, 61.01], [-148.99, 61.0]]
    rel = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
           "properties": {"type": "relation", "id": 77, "tags": {"natural": "water"}}}
    road = _feats("roads")
    got = build_catalog([rel], road, [], replace(cfg, pinned=("r77",)))
    assert [l.id for l in got] == ["r77"]


def test_no_roads_or_trails_only_pinned(layers, cfg):
    water = layers[0]
    assert build_catalog(water, [], [], cfg) == []
    assert [l.id for l in build_catalog(water, [], [], replace(cfg, pinned=("w1001",)))] == ["w1001"]


def test_catalog_roundtrip(tmp_path, layers, cfg):
    lakes = build_catalog(*layers, replace(cfg, pinned=("w1003",)))
    p = tmp_path / "lakes.geojson"
    write_catalog(lakes, p)
    assert json.loads(p.read_text())["type"] == "FeatureCollection"
    assert load_catalog(p) == lakes


def test_catalog_roundtrip_null_interior(tmp_path):
    from wildice.models import Lake
    lakes = [Lake("w1", None, 25.0, None, 0.5, 61.0, -149.0, None, "Lake too narrow for satellite readings")]
    p = tmp_path / "l.geojson"
    write_catalog(lakes, p)
    assert load_catalog(p) == lakes

