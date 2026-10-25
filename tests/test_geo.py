import pytest
from shapely.geometry import LineString, Point, box

from wildice.geo import LineIndex, area_acres, interior

SQUARE = box(-149.0, 61.0, -148.99, 61.01)  # 0.01 deg x 0.01 deg near 61N


def test_area_of_known_square():
    assert area_acres(SQUARE) == pytest.approx(148, rel=0.05)


def test_interior_shrinks():
    inner = interior(SQUARE, 30)
    assert inner is not None
    assert inner.area < SQUARE.area


def test_interior_too_small_none():
    strip = box(-149.0, 61.0, -149.0 + 60 / 53900, 61.01)  # ~60 m wide
    assert interior(strip, 30) is None


def test_interior_under_min_area_none():
    assert interior(SQUARE, 30, min_area_m2=1e9) is None


def test_nearest_miles():
    line = LineString([(-149.0, 60.99), (-149.0, 61.02)])
    pt = Point(-148.98, 61.0)
    assert LineIndex([line]).nearest_miles(pt) == pytest.approx(0.67, rel=0.05)


def test_nearest_miles_picks_closest_line():
    near = LineString([(-148.99, 60.99), (-148.99, 61.02)])
    far = LineString([(-149.5, 60.99), (-149.5, 61.02)])
    d = LineIndex([far, near]).nearest_miles(Point(-148.98, 61.0))
    assert d == pytest.approx(0.33, rel=0.05)


def test_nearest_miles_no_lines_none():
    assert LineIndex([]).nearest_miles(Point(-149, 61)) is None
