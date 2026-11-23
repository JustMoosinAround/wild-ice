"""Draw the lake's shoreline on its people-facing photo, so the lake stands out from
its neighbours. The photo covers photo_bbox(geometry) in plain lon/lat, so a point maps
to pixels linearly."""
from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw
from shapely.geometry import mapping, shape

from wildice.imagery import photo_bbox

OUTLINE = (108, 195, 218)  # the app's ice-cyan accent
SHORE_M = 30  # catalog outlines are shrunk this far from the shore (imagery.shore_buffer_m)


def _rings(geom: dict):
    g = mapping(shape(geom))
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"] if g["type"] == "MultiPolygon" else []
    for poly in polys:
        yield from poly


def outline_photo(png: bytes, geometry: dict) -> bytes:
    box, w, h = photo_bbox(geometry)
    lat = (box[1] + box[3]) / 2
    # grow the shrunk interior back out to about the shoreline (degrees, roughly)
    grown = shape(geometry).buffer(SHORE_M / (111_320 * math.cos(math.radians(lat))), join_style=2)
    im = Image.open(io.BytesIO(png)).convert("RGB")
    sx, sy = im.width / (box[2] - box[0]), im.height / (box[3] - box[1])
    draw = ImageDraw.Draw(im)
    width = max(2, round(im.width / 300))
    for ring in _rings(mapping(grown)):
        pts = [((x - box[0]) * sx, (box[3] - y) * sy) for x, y in ring]
        if len(pts) > 1:
            draw.line(pts + [pts[0]], fill=OUTLINE, width=width, joint="curve")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
