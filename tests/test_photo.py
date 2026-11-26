import io

import numpy as np
from PIL import Image

from wildice.imagery import photo_bbox
from wildice.photo import OUTLINE, outline_photo

LAKE = {"type": "Polygon", "coordinates": [[[-150.0, 61.0], [-149.99, 61.0], [-149.99, 61.005],
                                            [-150.0, 61.005], [-150.0, 61.0]]]}


def _png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (20, 30, 40)).save(buf, format="PNG")
    return buf.getvalue()


def test_outline_is_drawn_around_the_lake_in_the_middle():
    box, w, h = photo_bbox(LAKE)
    out = np.asarray(Image.open(io.BytesIO(outline_photo(_png(w, h), LAKE))).convert("RGB"))
    hit = np.all(out == OUTLINE, axis=-1)
    ys, xs = np.nonzero(hit)
    assert hit.sum() > 50
    # the outline sits in the middle of the photo: the lake is centred
    assert abs(xs.mean() - w / 2) < w * 0.1 and abs(ys.mean() - h / 2) < h * 0.1
    assert not hit[:5].any() and not hit[-5:].any()  # not at the edges


def test_photo_frames_a_small_lake_closer():
    box, w, h = photo_bbox(LAKE)
    span_m = (box[2] - box[0]) * 111320 * 0.4848
    assert 2000 <= span_m <= 3200


def _mask(w, h, boxes):
    a = np.zeros((h, w), np.uint8)
    for x0, y0, x1, y1 in boxes:
        a[y0:y1, x0:x1] = 255
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, format="PNG")
    return buf.getvalue()


def test_summer_water_outline_follows_the_lake_not_its_neighbour():
    from wildice.photo import outline_from_mask
    w, h = 200, 160
    mask = _mask(w, h, [(80, 60, 120, 100), (10, 10, 30, 30)])  # our lake, and a neighbour
    out = np.asarray(Image.open(io.BytesIO(outline_from_mask(_png(w, h), mask, (100, 80)))).convert("RGB"))
    hit = np.all(out == OUTLINE, axis=-1)
    ys, xs = np.nonzero(hit)
    assert hit.sum() > 40
    assert xs.min() >= 70 and xs.max() <= 130 and ys.min() >= 50 and ys.max() <= 110  # only around our lake
    assert not hit[85, 100]  # the lake itself isn't painted


def test_no_water_at_the_lake_gives_none():
    from wildice.photo import outline_from_mask
    assert outline_from_mask(_png(100, 100), _mask(100, 100, [(0, 0, 10, 10)]), (50, 50)) is None


def test_lake_point_in_photo_pixels():
    from wildice.photo import lake_pixel
    box, w, h = photo_bbox(LAKE)
    x, y = lake_pixel(LAKE, w, h)
    assert abs(x - w / 2) < w * 0.15 and abs(y - h / 2) < h * 0.15


def test_summer_trace_far_smaller_than_the_lake_falls_back():
    """Cheney Lake: the summer mask had only a puddle under the centre. A trace far off
    the mapped size isn't used (the caller draws the catalog outline instead)."""
    import io
    from PIL import Image, ImageDraw
    from wildice.photo import outline_from_mask
    img = Image.new("RGB", (200, 200), (90, 90, 90)); b = io.BytesIO(); img.save(b, "PNG")
    mask = Image.new("L", (200, 200), 0)
    ImageDraw.Draw(mask).rectangle((98, 98, 102, 102), fill=255)  # 25 px puddle
    m = io.BytesIO(); mask.save(m, "PNG")
    assert outline_from_mask(b.getvalue(), m.getvalue(), (100, 100), expected_px=4000) is None
    assert outline_from_mask(b.getvalue(), m.getvalue(), (100, 100), expected_px=30) is not None
