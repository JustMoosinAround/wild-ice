"""Crack and ridge lines on lake ice, from a true-color image at 10-20 m.

Owner's rule (from skating Skilak, Feb 2025): the tell for skateable ice is not a
black lake but a network of thin white lines, pressure ridges and cracks that caught
frost or snow. Open water can't show them, and snow cover hides them. Glacial lakes
are turquoise, not black, so brightness alone misses them.

Input: the truecolor.js PNG (reflectance x2.5, transparent outside the lake).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

GAIN = 2.5
OPEN_PX = 5          # lines thinner than this survive the opening as a top-hat
LINE_REFL = 0.03     # a line pixel is this much brighter than its opened surroundings
THIN_WINDOW = 9      # ...and line pixels cover under THIN_MAX of a window this size
THIN_MAX = 0.45      # (wide drifts and snow patches are not thin)
SHORE_PX = 4         # drop this many pixels inside the shore (shore snow, shadows)


@dataclass(frozen=True)
class CrackStats:
    line_frac: float     # share of the lake covered by thin bright lines
    background: float    # median reflectance of the lake between the lines
    lake_px: int


def _filter(a: np.ndarray, f) -> np.ndarray:
    return np.asarray(Image.fromarray(a).filter(f))


def crack_stats_array(rgba: np.ndarray) -> CrackStats | None:
    """rgba: uint8 HxWx4 true-color image, alpha > 0 on the lake."""
    lum8 = rgba[..., :3].astype(np.float32).mean(-1).clip(0, 255).astype(np.uint8)
    lake = rgba[..., 3] > 127
    core = _filter((lake * 255).astype(np.uint8), ImageFilter.MinFilter(2 * SHORE_PX + 1)) > 127
    n = int(core.sum())
    if n < 200:  # small lake: trim less of the shore
        core = lake
        n = int(core.sum())
        if n < 200:
            return None
    # Morphological opening (min then max) removes features thinner than OPEN_PX.
    opened = _filter(_filter(lum8, ImageFilter.MinFilter(OPEN_PX)), ImageFilter.MaxFilter(OPEN_PX))
    tophat = (lum8.astype(np.float32) - opened.astype(np.float32)) / 255 / GAIN
    line = (tophat > LINE_REFL) & core
    density = _filter((line * 255).astype(np.uint8), ImageFilter.BoxBlur(THIN_WINDOW // 2)) / 255
    thin = line & (density < THIN_MAX)
    lum = lum8.astype(np.float32) / 255 / GAIN
    rest = core & ~line
    background = float(np.median(lum[rest])) if rest.any() else float(np.median(lum[core]))
    return CrackStats(round(float(thin.sum()) / n, 4), round(background, 3), n)


def crack_stats(png: bytes) -> CrackStats | None:
    try:
        img = Image.open(io.BytesIO(png)).convert("RGBA")
    except (OSError, ValueError):  # not an image (error body, truncated download)
        return None
    return crack_stats_array(np.asarray(img))


# --- daily checks ---------------------------------------------------------------

def image_size(geometry: dict, res_m: float, max_px: int) -> tuple[int, int]:
    """Pixels for a ~res_m image of the lake's bounding box, capped at max_px."""
    import math
    from shapely.geometry import shape
    minx, miny, maxx, maxy = shape(geometry).bounds
    w_m = (maxx - minx) * 111_320 * math.cos(math.radians((miny + maxy) / 2))
    h_m = (maxy - miny) * 110_540
    scale = max(1.0, max(w_m, h_m) / res_m / max_px)
    return (min(max_px, max(32, round(w_m / res_m / scale))),
            min(max_px, max(32, round(h_m / res_m / scale))))


def check_cracks(client, lakes, imagery, ice, s2_history, checked, cfg, budget) -> dict:
    """Look for a crack network on today's newest clear, not-white Sentinel-2 look of
    each lake thick enough to skate. Marks that day CRACKED in s2_history when the
    lines cover at least crack_min_frac. `checked` ({lake: {day: frac}}) keeps each
    look from being fetched twice. Returns {lake_id: day} for the cracked ones."""
    from wildice.models import SurfaceClass
    from wildice.score import classify_s2
    im = cfg.imagery
    found: dict = {}
    done = 0
    for lake_id, img in imagery.items():
        lake = lakes.get(lake_id)
        if lake is None or lake.interior is None or ice[lake_id].thickness_cm < cfg.ice.skate_cm:
            continue
        looks = [o for o in img.s2 if classify_s2(o, cfg) in (SurfaceClass.DARK, SurfaceClass.GREY)]
        if not looks:
            continue
        day = max(o.day for o in looks)
        seen = checked.setdefault(lake_id, {})
        if day.isoformat() in seen:
            continue
        if done >= im.crack_checks_per_run or budget.remaining() < 1:
            break
        w, h = image_size(lake.interior, im.crack_res_m, im.crack_max_px)
        png = client.truecolor_png(lake.interior, day, "s2", w, h)  # the client counts it
        done += 1
        st = crack_stats(png)
        seen[day.isoformat()] = st.line_frac if st else 0.0
        if st and st.line_frac >= im.crack_min_frac:
            s2_history.setdefault(lake_id, {})[day] = SurfaceClass.CRACKED
            found[lake_id] = day
    return found
