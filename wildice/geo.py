"""Geometry helpers. Inputs/outputs are EPSG:4326; math is done in EPSG:3338 (Alaska Albers)."""
from __future__ import annotations

import numpy as np
import shapely
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry.base import BaseGeometry

_M2_PER_ACRE = 4046.8564224
_M_PER_MILE = 1609.344

_TO_AK = Transformer.from_crs("EPSG:4326", "EPSG:3338", always_xy=True)
_FROM_AK = Transformer.from_crs("EPSG:3338", "EPSG:4326", always_xy=True)


def _reproject(geom: BaseGeometry, tr: Transformer) -> BaseGeometry:
    return shapely.transform(geom, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))


def _project(geom: BaseGeometry) -> BaseGeometry:
    return _reproject(geom, _TO_AK)


def area_acres(geom: BaseGeometry) -> float:
    return _project(geom).area / _M2_PER_ACRE


def interior(geom: BaseGeometry, buffer_m: float, min_area_m2: float = 2000) -> BaseGeometry | None:
    """Shrink a lake by buffer_m; None if nothing usable (< min_area_m2) is left."""
    shrunk = _project(geom).buffer(-buffer_m)
    if shrunk.is_empty or shrunk.area < min_area_m2:
        return None
    return _reproject(shrunk, _FROM_AK)


class LineIndex:
    """Nearest-distance lookup over a set of lines."""

    def __init__(self, lines: list[BaseGeometry]):
        self._lines = [_project(g) for g in lines]
        self._tree = STRtree(self._lines) if self._lines else None

    def nearest_miles(self, geom: BaseGeometry) -> float | None:
        if self._tree is None:
            return None
        g = _project(geom)
        idx = self._tree.nearest(g)
        return float(g.distance(self._lines[idx])) / _M_PER_MILE
