"""Find grey-ice / black-patch zones on a lake's true-color thumbnail.

The thumbnail (truecolor.js) is Sentinel-2 or Landsat true color x2.5, transparent
outside the lake. On 344 thumbnails from fall 2026, open-water lakes were ~97% black;
patchy lakes had sizable black and grey zones side by side.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter

GAIN = 2.5           # truecolor.js display gain
BLACK_REFL = 0.07    # below: black (open water or new black ice)
WHITE_REFL = 0.30    # at or above: snow
MIN_ZONE = 0.15      # each of black and grey must cover this share of the lake
TINT = (255, 120, 0)  # orange shading over the black patch


def _load(png: bytes) -> tuple[Image.Image, np.ndarray, np.ndarray]:
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    a = np.asarray(im).astype(float) / 255
    lake = a[..., 3] > 0.5
    # median filter: zones, not single noisy pixels
    lum = Image.fromarray((a[..., :3].mean(-1) * 255).astype(np.uint8)).filter(
        ImageFilter.MedianFilter(5))
    refl = np.asarray(lum).astype(float) / 255 / GAIN
    return im, lake, refl


def analyze(png: bytes) -> dict | None:
    """Shares of the lake that are black, grey and white; None if too little lake shows."""
    _, lake, refl = _load(png)
    if lake.sum() < 50:
        return None
    v = refl[lake]
    black = float((v < BLACK_REFL).mean())
    white = float((v >= WHITE_REFL).mean())
    grey = 1.0 - black - white
    return {"black": round(black, 3), "grey": round(grey, 3), "white": round(white, 3),
            "mixed": black >= MIN_ZONE and grey >= MIN_ZONE}


def overlay(png: bytes) -> bytes:
    """The thumbnail with its black patch shaded orange."""
    im, lake, refl = _load(png)
    a = np.asarray(im).copy()
    patch = lake & (refl < BLACK_REFL)
    rgb = a[..., :3].astype(float)
    rgb[patch] = rgb[patch] * 0.45 + np.array(TINT) * 0.55
    a[..., :3] = rgb.astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(a, "RGBA").save(out, format="PNG", optimize=True)
    return out.getvalue()
