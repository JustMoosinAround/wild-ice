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
