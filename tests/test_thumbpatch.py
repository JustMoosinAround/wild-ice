import io

import numpy as np
from PIL import Image

from wildice import thumbpatch


def _png(left_refl, right_refl, size=64):
    a = np.zeros((size, size, 4), dtype=np.uint8)
    a[..., 3] = 0
    a[8:56, 8:56, 3] = 255  # the lake
    a[:, : size // 2, :3] = int(min(255, left_refl * 2.5 * 255))
    a[:, size // 2:, :3] = int(min(255, right_refl * 2.5 * 255))
    out = io.BytesIO()
    Image.fromarray(a, "RGBA").save(out, format="PNG")
    return out.getvalue()


def test_even_black_lake_is_not_mixed():
    r = thumbpatch.analyze(_png(0.03, 0.03))
    assert r["black"] > 0.95 and r["mixed"] is False


def test_grey_and_black_halves_are_mixed():
    r = thumbpatch.analyze(_png(0.03, 0.15))
    assert 0.4 < r["black"] < 0.6 and 0.4 < r["grey"] < 0.6 and r["mixed"] is True


def test_snow_and_black_is_not_grey_mixed():
    r = thumbpatch.analyze(_png(0.03, 0.6))
    assert r["white"] > 0.4 and r["mixed"] is False


def test_tiny_lake_skipped():
    a = np.zeros((64, 64, 4), dtype=np.uint8)
    a[0:3, 0:3, 3] = 255
    buf = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buf, format="PNG")
    assert thumbpatch.analyze(buf.getvalue()) is None


def test_overlay_shades_only_the_black_patch():
    img = np.asarray(Image.open(io.BytesIO(thumbpatch.overlay(_png(0.03, 0.15)))))
    left, right = img[30, 16], img[30, 48]
    assert left[0] > 100 and left[0] > left[2]          # orange tint on the black half
    assert abs(int(right[0]) - int(right[2])) < 5       # grey half unchanged
    assert img[2, 2, 3] == 0                            # outside the lake stays clear
