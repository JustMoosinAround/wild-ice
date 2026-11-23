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
