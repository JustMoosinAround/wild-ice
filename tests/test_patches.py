from datetime import date, timedelta
from pathlib import Path

from wildice.config import load_config
from wildice.models import Confidence, DayWeather, ImageryStats, Label, S2Obs, Score
from wildice.patches import apply_patches, texture_by_day

CFG = load_config(Path(__file__).resolve().parent.parent / "config.yaml")
RUN = date(2026, 2, 10)
PATCHY, EVEN = 0.03, 0.003


def _score(label=Label.LIKELY_BLACK_ICE, conf=Confidence.HIGH, h=25.0):
    return Score("w1", label, conf, "~25 cm est.", h, RUN - timedelta(days=1))


def _cold(start, end, t=-10.0):
    out, d = [], start
    while d <= end:
        out.append(DayWeather(d, t - 3, t + 3, t, 0.0, 0.0, 10.0))
        d += timedelta(days=1)
    return out


WX = _cold(date(2025, 10, 1), RUN)


def test_texture_merges_history_with_todays_clear_looks():
    dark = (0.9, 0.05, 0.04, 0.02)
    im = ImageryStats((S2Obs(RUN, *dark, texture=PATCHY),
                       S2Obs(RUN - timedelta(days=1), 0.2, *dark[1:], texture=0.5),  # cloudy
                       S2Obs(RUN - timedelta(days=2), *dark)), (), None)
    hist = {RUN - timedelta(days=5): EVEN}
    assert texture_by_day(hist, im, CFG) == {RUN - timedelta(days=5): EVEN, RUN: PATCHY}


def test_patchy_latest_look_caps_confidence():
    sc = apply_patches(_score(), {RUN - timedelta(days=1): PATCHY}, WX, RUN, CFG)
    assert sc.label is Label.LIKELY_BLACK_ICE and sc.confidence is Confidence.MEDIUM
    assert "patchy on Feb 9 image" in sc.reason and "open water or newer, thinner ice" in sc.reason


def test_even_lake_untouched():
    sc = apply_patches(_score(), {RUN - timedelta(days=1): EVEN}, WX, RUN, CFG)
    assert sc == _score()


def test_patch_that_evened_out_gets_new_ice_estimate():
    tex = {RUN - timedelta(days=3): PATCHY, RUN - timedelta(days=1): EVEN}
    mild = _cold(date(2025, 10, 1), RUN, t=-3.0)  # 3 mild days grow only a few cm
    sc = apply_patches(_score(), tex, mild, RUN, CFG)
    assert sc.label is Label.FREEZING and sc.confidence is Confidence.MEDIUM
    assert "black patch seen Feb 7 has evened out: newer ice there, ~" in sc.reason


def test_old_evened_patch_has_had_time_to_thicken():
    tex = {RUN - timedelta(days=20): PATCHY, RUN - timedelta(days=1): EVEN}
    sc = apply_patches(_score(), tex, WX, RUN, CFG)
    assert sc.label is Label.LIKELY_BLACK_ICE and "black patch seen Jan 21" in sc.reason


def test_patches_older_than_the_memory_are_forgotten():
    tex = {RUN - timedelta(days=CFG.imagery.patch_days + 1): PATCHY,
           RUN - timedelta(days=1): EVEN}
    assert apply_patches(_score(), tex, WX, RUN, CFG) == _score()


def test_open_water_stays_open_water():
    sc = apply_patches(_score(Label.OPEN_WATER, Confidence.MEDIUM, 0.0),
                       {RUN - timedelta(days=1): PATCHY}, WX, RUN, CFG)
    assert sc.label is Label.OPEN_WATER and "patchy" in sc.reason
