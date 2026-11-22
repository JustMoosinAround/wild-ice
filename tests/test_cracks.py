import numpy as np

from wildice.cracks import crack_stats_array


def _img(base, line=None, drift=False):
    a = np.full((300, 300), base, float)
    if line is not None:
        for k in range(10, 300, 25):
            a[k:k + 2, :] = line
            a[:, k:k + 1] = line
    if drift:
        a[100:160, :] = 0.5
    v = (a * 2.5 * 255).clip(0, 255).astype(np.uint8)
    return np.dstack([v, v, v, np.full_like(v, 255)])


def test_thin_white_lines_on_ice_are_found():
    st = crack_stats_array(_img(0.12, line=0.3))
    assert st.line_frac > 0.05 and st.background < 0.15


def test_open_water_snow_and_wide_drifts_have_no_lines():
    for img in (_img(0.04), _img(0.6), _img(0.12, drift=True)):
        assert crack_stats_array(img).line_frac == 0.0


def test_too_small_a_lake_gives_nothing():
    img = _img(0.12, line=0.3)
    img[..., 3] = 0
    img[:10, :10, 3] = 255
    assert crack_stats_array(img) is None


# --- daily checks ---------------------------------------------------------------
import io
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from wildice.config import load_config
from wildice.cracks import check_cracks, image_size
from wildice.models import IceState, ImageryStats, Lake, S2Obs, SurfaceClass

CFG = load_config(Path(__file__).resolve().parent.parent / "config.yaml")
RUN = date(2026, 2, 10)
BOX = {"type": "Polygon", "coordinates": [[[-149.5, 61.0], [-149.45, 61.0], [-149.45, 61.02],
                                           [-149.5, 61.02], [-149.5, 61.0]]]}


def _png(img):
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


class _Client:
    def __init__(self, png):
        self.png, self.calls = png, []

    def truecolor_png(self, geometry, day, sensor="s2", width=256, height=256):
        self.calls.append((day, width, height))
        return self.png


class _Budget:
    def __init__(self, n):
        self.n, self.used = n, 0

    def remaining(self):
        return self.n - self.used

    def record(self, k=1):
        self.used += k


def _lake(i="w1"):
    return Lake(i, "L", 100, 1, None, 61.0, -149.5, BOX, None)


def _ice(cm):
    return IceState(100, cm, RUN - timedelta(days=20), None, 0.0, None, ())


GREY_OBS = S2Obs(RUN - timedelta(days=1), 0.95, 0.2, 0.2, 0.1)


def test_image_size_is_about_10_m_and_capped():
    w, h = image_size(BOX, 10.0, 1500)
    assert 250 <= w <= 290 and 200 <= h <= 240
    big = {"type": "Polygon", "coordinates": [[[-150.6, 60.3], [-150.1, 60.3], [-150.1, 60.5],
                                               [-150.6, 60.5], [-150.6, 60.3]]]}
    assert max(image_size(big, 10.0, 1500)) == 1500


def test_cracked_grey_look_becomes_cracked_and_is_checked_once():
    client = _Client(_png(_img(0.12, line=0.3)))
    hist, checked, budget = {"w1": {GREY_OBS.day: SurfaceClass.GREY}}, {}, _Budget(10)
    imagery = {"w1": ImageryStats((GREY_OBS,), (), None)}
    found = check_cracks(client, {"w1": _lake()}, imagery, {"w1": _ice(20)}, hist, checked,
                         CFG, budget)
    assert hist["w1"][GREY_OBS.day] is SurfaceClass.CRACKED
    assert found == {"w1": GREY_OBS.day} and len(client.calls) == 1
    assert checked["w1"][GREY_OBS.day.isoformat()] > CFG.imagery.crack_min_frac
    check_cracks(client, {"w1": _lake()}, imagery, {"w1": _ice(20)}, hist, checked, CFG, budget)
    assert len(client.calls) == 1


def test_no_lines_thin_ice_white_or_no_budget_leave_it_alone():
    imagery = {"w1": ImageryStats((GREY_OBS,), (), None)}
    for png, cm, n in ((_img(0.12), 20, 10), (_img(0.12, line=0.3), 3, 10),
                       (_img(0.12, line=0.3), 20, 0)):
        client, hist = _Client(_png(png)), {"w1": {GREY_OBS.day: SurfaceClass.GREY}}
        check_cracks(client, {"w1": _lake()}, imagery, {"w1": _ice(cm)}, hist, {}, CFG, _Budget(n))
        assert hist["w1"][GREY_OBS.day] is SurfaceClass.GREY
    white = S2Obs(RUN - timedelta(days=1), 0.95, 0.6, 0.6, 0.1)
    client = _Client(_png(_img(0.12, line=0.3)))
    check_cracks(client, {"w1": _lake()}, {"w1": ImageryStats((white,), (), None)},
                 {"w1": _ice(20)}, {"w1": {}}, {}, CFG, _Budget(10))
    assert client.calls == []


def test_unreadable_image_is_no_result():
    from wildice.cracks import crack_stats
    assert crack_stats(b"\x89PNG fake") is None
