"""Draw the lake's shoreline on its people-facing photo, so the lake stands out from
its neighbours. The photo covers photo_bbox(geometry) in plain lon/lat, so a point maps
to pixels linearly."""
from __future__ import annotations

import io
import math

import numpy as np

from PIL import Image, ImageDraw
from shapely.geometry import mapping, shape

from wildice.imagery import photo_bbox

OUTLINE = (108, 195, 218)  # the app's ice-cyan accent
HALO = (4, 9, 12)          # the app's night-black
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
    # a dark halo under a bold cyan line: reads on snow, forest and town alike
    width = max(3, round(im.width / 160))
    rings = [[((x - box[0]) * sx, (box[3] - y) * sy) for x, y in ring] for ring in _rings(mapping(grown))]
    for fill, wd in ((HALO, width + 4), (OUTLINE, width)):
        for pts in rings:
            if len(pts) > 1:
                draw.line(pts + [pts[0]], fill=fill, width=wd, joint="curve")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def lake_pixel(geometry: dict, width: int, height: int) -> tuple[int, int]:
    """A point inside the lake, in the photo's pixels."""
    box, _, _ = photo_bbox(geometry)
    pt = shape(geometry).representative_point()
    return (round((pt.x - box[0]) / (box[2] - box[0]) * (width - 1)),
            round((box[3] - pt.y) / (box[3] - box[1]) * (height - 1)))


def outline_from_mask(png: bytes, mask_png: bytes, seed: tuple[int, int]) -> bytes | None:
    """Draw the shoreline of the summer water body under `seed` (open water in July or
    August, so it's right even when the lake and the land are snowed over).
    None if there's no water at or right next to the seed."""
    from PIL import ImageFilter
    im = Image.open(io.BytesIO(png)).convert("RGB")
    mask = Image.open(io.BytesIO(mask_png)).convert("L").resize(im.size, Image.NEAREST)
    water = mask.point(lambda v: 255 if v > 127 else 0)
    x0, y0 = seed
    start = None
    for r in range(0, 6):  # small lakes: the seed may land a pixel off the water
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                x, y = x0 + dx, y0 + dy
                if 0 <= x < im.width and 0 <= y < im.height and water.getpixel((x, y)) == 255:
                    start = (x, y)
                    break
            if start:
                break
        if start:
            break
    if start is None:
        return None
    ImageDraw.floodfill(water, start, 128)  # our lake only: neighbours stay 255
    lake = water.point(lambda v: 255 if v == 128 else 0)
    edge = Image.fromarray(
        ((np.asarray(lake) > 0) & ~(np.asarray(lake.filter(ImageFilter.MinFilter(3))) > 0)).astype("uint8") * 255)
    width = max(3, round(im.width / 160)) | 1
    line = edge.filter(ImageFilter.MaxFilter(width))
    halo = edge.filter(ImageFilter.MaxFilter(width + 4))
    im.paste(Image.new("RGB", im.size, HALO), mask=halo)
    im.paste(Image.new("RGB", im.size, OUTLINE), mask=line)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
