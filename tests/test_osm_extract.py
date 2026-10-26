import os
import time
from pathlib import Path

import pytest
import requests
import responses

from wildice.catalog import build_catalog
from wildice.config import load_config
from wildice.osm_extract import EXTRACT_URL, USER_AGENT, download_extract, read_layers

FIX = Path(__file__).parent / "fixtures"
OSM = FIX / "extract_small.osm"
BOX = (61.0, -150.0, 61.5, -149.0)  # south, west, north, east


def ids(feats):
    return sorted((f["properties"]["type"], f["properties"]["id"]) for f in feats)


def test_water_lakes_from_ways_and_relations():
    water, _, _ = read_layers(OSM, BOX)
    # w100 closed-way lake and r500 multipolygon lake; river (w300) and the
    # out-of-box pond (w301) are skipped.
    assert ids(water) == [("relation", 500), ("way", 100)]


def test_water_feature_shape_matches_build_catalog_input():
    water, _, _ = read_layers(OSM, BOX)
    lake = next(f for f in water if f["properties"]["id"] == 100)
    assert lake["type"] == "Feature"
    assert lake["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert lake["properties"]["tags"]["name"] == "Test Lake"


def test_roads_and_trails():
    _, roads, trails = read_layers(OSM, BOX)
    assert ids(roads) == [("way", 400)]
    assert ids(trails) == [("way", 401), ("way", 402)]
    assert all(f["geometry"]["type"] == "LineString" for f in roads + trails)


def test_layers_feed_build_catalog():
    cfg = load_config(Path(__file__).parent.parent / "config.yaml")
    lakes = build_catalog(*read_layers(OSM, BOX), cfg)
    by_id = {lake.id: lake for lake in lakes}
    assert set(by_id) == {"w100", "r500"}
    assert by_id["w100"].name == "Test Lake"


@responses.activate
def test_download_saves_file_with_app_name(tmp_path):
    responses.get(EXTRACT_URL, body=b"PBFDATA")
    path = tmp_path / "alaska.osm.pbf"
    download_extract(path, requests.Session())
    assert path.read_bytes() == b"PBFDATA"
    assert responses.calls[0].request.headers["User-Agent"] == USER_AGENT
    assert not list(tmp_path.glob("*.part"))


@responses.activate
def test_recent_download_is_reused(tmp_path):
    path = tmp_path / "alaska.osm.pbf"
    path.write_bytes(b"OLD")
    download_extract(path, requests.Session())
    assert len(responses.calls) == 0 and path.read_bytes() == b"OLD"


@responses.activate
def test_stale_download_is_replaced(tmp_path):
    responses.get(EXTRACT_URL, body=b"NEW")
    path = tmp_path / "alaska.osm.pbf"
    path.write_bytes(b"OLD")
    week_ago = time.time() - 8 * 24 * 3600
    os.utime(path, (week_ago, week_ago))
    download_extract(path, requests.Session())
    assert path.read_bytes() == b"NEW"


@responses.activate
def test_failed_download_keeps_no_partial_file(tmp_path):
    responses.get(EXTRACT_URL, status=503)
    path = tmp_path / "alaska.osm.pbf"
    with pytest.raises(requests.HTTPError):
        download_extract(path, requests.Session())
    assert not path.exists() and not list(tmp_path.glob("*.part"))
