import math
from pathlib import Path

import pytest

from wildice.catalog import load_catalog, write_catalog
from wildice.depths import DepthPoint, attach_depths, load_points
from wildice.icemodel import water_lag_days
from wildice.models import Lake

# ~40 acres (0.0035 deg lat x 0.0072 deg lon at 61 N)
POLY = {"type": "Polygon", "coordinates": [[[-149.5, 61.0], [-149.4928, 61.0],
                                             [-149.4928, 61.0035], [-149.5, 61.0035],
                                             [-149.5, 61.0]]]}
LAKE = Lake("w1", "Test", 40.0, 0.1, None, 61.0017, -149.4964, POLY, None)


def test_load_points_reads_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("hylak_id,lake_name,area_km2,depth_avg_m,pour_lon,pour_lat\n"
                 "7,Test,0.16,6.5,-149.5,61.0\n")
    assert load_points(p) == [DepthPoint(7, "Test", 0.16, 6.5, -149.5, 61.0)]


def test_outlet_point_on_shore_matches_similar_area():
    pt = DepthPoint(7, "", 40 / 247.105, 6.5, -149.5001, 61.001)  # just outside west shore
    (out,) = attach_depths([LAKE], [pt])
    assert out.depth_m == 6.5


def test_far_or_wrong_size_points_do_not_match():
    far = DepthPoint(1, "", 40 / 247.105, 6.5, -149.40, 61.0)
    huge = DepthPoint(2, "", 4000 / 247.105, 30.0, -149.4964, 61.0017)
    (out,) = attach_depths([LAKE], [far, huge])
    assert out.depth_m is None


def test_closest_area_wins():
    a = DepthPoint(1, "", 100 / 247.105, 9.0, -149.4964, 61.0017)
    b = DepthPoint(2, "", 45 / 247.105, 5.0, -149.4964, 61.0017)
    (out,) = attach_depths([LAKE], [a, b])
    assert out.depth_m == 5.0


def test_depth_can_only_slow_cooling():
    area_lag = -18 + 15 * math.log10(40)
    assert water_lag_days(40, None) == pytest.approx(area_lag)
    assert water_lag_days(40, 12.0) == pytest.approx(3.64 * 12 ** 0.64, rel=1e-3)  # deep pond
    assert water_lag_days(40, 1.0) == pytest.approx(area_lag)                        # shallow
    assert water_lag_days(14000, 20.6) == water_lag_days(14000, None)  # Lake Louise: fetch
    assert water_lag_days(14000, 75.0) == 50.0                          # capped
    assert water_lag_days(5, 0.3) == 5.0                                # floor


def test_catalog_round_trips_depth(tmp_path):
    p = tmp_path / "lakes.geojson"
    write_catalog([attach_depths([LAKE], [DepthPoint(7, "", 40 / 247.105, 6.5, -149.4964,
                                                     61.0017)])[0], LAKE], p)
    a, b = load_catalog(p)
    assert a.depth_m == 6.5 and b.depth_m is None


def test_repo_extract_loads():
    pts = load_points(Path(__file__).resolve().parent.parent / "data" / "hydrolakes_southcentral.csv")
    assert len(pts) > 2000 and all(p.depth_avg_m > 0 for p in pts)
