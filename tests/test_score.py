from datetime import date, timedelta
from pathlib import Path

from wildice.config import load_config
from wildice.models import (
    Confidence, IceState, ImageryStats, Label, Lake, LSObs, ResetEvent, ResetKind, S1Obs, S2Obs,
    SurfaceClass,
)
from wildice.score import (
    classify_ls, classify_s2, optical_classes, s1_frozen, score_lake, valid_ls_classes,
    valid_s2_classes,
)

cfg = load_config(Path("config.yaml"))
RUN = date(2026, 2, 10)  # outside the low-sun window
D = RUN
lake = Lake("w1", "Test", 50, 1, None, 61, -149, None, None)
DARK = (.9, .05, .04, .02)
WHITE = (.9, .6, .6, .1)
GREY = (.9, .2, .2, .1)


def ice(h=12, snow=0.0, reset=None, last_snow=None, possible=()):
    return IceState(100, h, None, reset, snow, last_snow, tuple(possible))


def img(days_ago, vals, s1=(), base=None):
    s2 = (S2Obs(RUN - timedelta(days=days_ago), *vals),) if vals else ()
    return ImageryStats(s2, tuple(s1), base)


def test_classify_white(): assert classify_s2(S2Obs(D, .9, .6, .6, .1), cfg) is SurfaceClass.WHITE
def test_classify_dark(): assert classify_s2(S2Obs(D, .9, .05, .04, .02), cfg) is SurfaceClass.DARK
def test_classify_grey(): assert classify_s2(S2Obs(D, .9, .2, .2, .1), cfg) is SurfaceClass.GREY
def test_classify_cloudy_none(): assert classify_s2(S2Obs(D, .5, .05, .04, .02), cfg) is None


def test_classify_zero_denominator():
    assert classify_s2(S2Obs(D, .9, 0, 0, 0), cfg) is SurfaceClass.DARK


def test_valid_s2_classes():
    im = ImageryStats((S2Obs(D, .9, .6, .6, .1), S2Obs(D - timedelta(days=1), .1, .6, .6, .1)), (), None)
    assert valid_s2_classes(im, cfg) == {D: SurfaceClass.WHITE}
    assert valid_s2_classes(None, cfg) == {}


def test_s1_frozen(): assert s1_frozen(S1Obs(D, -15), -20, cfg) is True
def test_s1_open(): assert s1_frozen(S1Obs(D, -19), -20, cfg) is False
def test_s1_no_baseline(): assert s1_frozen(S1Obs(D, -15), None, cfg) is None


def test_open_water():
    assert score_lake(lake, ice(h=1), None, RUN, cfg).label is Label.OPEN_WATER


def test_snow_by_weather_low():
    s = score_lake(lake, ice(snow=3, last_snow=RUN - timedelta(days=2)), None, RUN, cfg)
    assert (s.label, s.confidence) == (Label.SNOW_COVERED, Confidence.LOW)


def test_snow_weather_overridden_by_later_clear_image():
    s = score_lake(lake, ice(snow=3, last_snow=RUN - timedelta(days=4)), img(1, DARK), RUN, cfg)
    assert s.label is not Label.SNOW_COVERED


def test_white_image_high():
    s = score_lake(lake, ice(), img(1, WHITE), RUN, cfg)
    assert (s.label, s.confidence) == (Label.SNOW_COVERED, Confidence.HIGH)


def test_freezing():
    assert score_lake(lake, ice(h=6), None, RUN, cfg).label is Label.FREEZING


def test_black_ice_fresh_dark_high():
    s = score_lake(lake, ice(), img(1, DARK), RUN, cfg)
    assert (s.label, s.confidence) == (Label.LIKELY_BLACK_ICE, Confidence.HIGH)
    assert "~12 cm est." in s.reason and "dark on" in s.reason
    assert s.last_clear_day == RUN - timedelta(days=1)


def test_black_ice_old_dark_medium():
    assert score_lake(lake, ice(), img(5, DARK), RUN, cfg).confidence is Confidence.MEDIUM


def test_black_ice_radar_only_medium():
    im = img(0, None, s1=[S1Obs(RUN - timedelta(days=1), -15)], base=-20)
    s = score_lake(lake, ice(), im, RUN, cfg)
    assert (s.label, s.confidence) == (Label.LIKELY_BLACK_ICE, Confidence.MEDIUM)
    assert "radar suggests ice" in s.reason


def test_radar_ignored_when_s2_in_window():
    im = ImageryStats((S2Obs(RUN - timedelta(days=5), *GREY),), (S1Obs(RUN, -15),), -20)
    assert score_lake(lake, ice(), im, RUN, cfg).label is Label.UNKNOWN


def test_no_imagery_unknown_low():
    s = score_lake(lake, ice(), None, RUN, cfg)
    assert (s.label, s.confidence) == (Label.UNKNOWN, Confidence.LOW)
    assert "no clear image" in s.reason


def test_grey_is_unknown():
    assert score_lake(lake, ice(), img(1, GREY), RUN, cfg).label is Label.UNKNOWN


def test_likely_reset_caps_medium():
    r = ResetEvent(RUN - timedelta(days=8), ResetKind.LIKELY)
    s = score_lake(lake, ice(reset=r), img(1, DARK), RUN, cfg)
    assert s.label is Label.LIKELY_BLACK_ICE and s.confidence is Confidence.MEDIUM
    assert "no snow since rain/thaw on Feb 2" in s.reason


def test_reason_dates_have_no_leading_zero():
    im = ImageryStats((S2Obs(date(2026, 3, 5), *DARK),), (), None)
    s = score_lake(lake, ice(), im, date(2026, 3, 6), cfg)
    assert "dark on Mar 5 image" in s.reason


def test_reason_snow_part():
    r = ResetEvent(date(2026, 2, 2), ResetKind.FREEZE_UP)
    s = score_lake(lake, ice(snow=4, reset=r, last_snow=RUN), None, RUN, cfg)
    assert "4 cm snow since Feb 2" in s.reason


def test_reason_mentions_possible_reset():
    pr = ResetEvent(date(2026, 11, 6), ResetKind.POSSIBLE)
    s = score_lake(lake, ice(possible=[pr]), None, date(2026, 11, 10), cfg)
    assert "possible wind clearing Nov 6" in s.reason


def test_reason_snow_no_reset_says_last_on():
    s = score_lake(lake, ice(snow=3, last_snow=date(2026, 2, 8)), None, RUN, cfg)
    assert "3 cm snow, last on Feb 8" in s.reason
    assert "snow since" not in s.reason


def test_radar_phrase_absent_for_open_water():
    im = img(0, None, s1=[S1Obs(RUN, -15)], base=-20)
    s = score_lake(lake, ice(h=1), im, RUN, cfg)
    assert s.label is Label.OPEN_WATER and "radar" not in s.reason


def test_radar_open_caps_dark_at_medium():
    im = img(1, DARK, s1=[S1Obs(RUN - timedelta(days=1), -19.5)], base=-20)
    s = score_lake(lake, ice(), im, RUN, cfg)
    assert (s.label, s.confidence) == (Label.LIKELY_BLACK_ICE, Confidence.MEDIUM)
    assert s.reason.endswith("radar does not confirm ice")


def test_radar_frozen_keeps_dark_high():
    im = img(1, DARK, s1=[S1Obs(RUN - timedelta(days=1), -15)], base=-20)
    s = score_lake(lake, ice(), im, RUN, cfg)
    assert (s.label, s.confidence) == (Label.LIKELY_BLACK_ICE, Confidence.HIGH)
    assert "radar does not confirm" not in s.reason


def test_radar_without_baseline_does_not_cap():
    im = img(1, DARK, s1=[S1Obs(RUN - timedelta(days=1), -19.5)], base=None)
    assert score_lake(lake, ice(), im, RUN, cfg).confidence is Confidence.HIGH


def test_radar_uses_latest_s1_only():
    s1 = [S1Obs(RUN - timedelta(days=6), -19.5), S1Obs(RUN - timedelta(days=1), -15)]
    assert score_lake(lake, ice(), img(1, DARK, s1=s1, base=-20), RUN, cfg).confidence \
        is Confidence.HIGH


def test_low_sun_dark_capped_at_medium():
    run = date(2025, 12, 10)
    im = ImageryStats((S2Obs(run - timedelta(days=1), *DARK),), (), None)
    s = score_lake(lake, ice(), im, run, cfg)
    assert (s.label, s.confidence) == (Label.LIKELY_BLACK_ICE, Confidence.MEDIUM)
    assert s.reason.endswith("low sun")


def test_low_sun_window_wraps_new_year():
    for day, inside in ((date(2025, 11, 24), False), (date(2025, 11, 25), True),
                        (date(2025, 12, 31), True), (date(2026, 1, 1), True),
                        (date(2026, 1, 15), True), (date(2026, 1, 16), False)):
        im = ImageryStats((S2Obs(day, *DARK),), (), None)
        s = score_lake(lake, ice(), im, day + timedelta(days=1), cfg)
        assert (s.confidence is Confidence.MEDIUM) is inside, day
        assert ("low sun" in s.reason) is inside, day


def test_low_sun_and_radar_both_noted():
    run = date(2025, 12, 10)
    im = ImageryStats((S2Obs(run - timedelta(days=1), *DARK),),
                      (S1Obs(run, -19.5),), -20)
    s = score_lake(lake, ice(), im, run, cfg)
    assert s.confidence is Confidence.MEDIUM
    assert "radar does not confirm ice" in s.reason and "low sun" in s.reason


def test_low_sun_does_not_touch_snow_label():
    run = date(2025, 12, 10)
    im = ImageryStats((S2Obs(run - timedelta(days=1), *WHITE),), (), None)
    s = score_lake(lake, ice(), im, run, cfg)
    assert (s.label, s.confidence) == (Label.SNOW_COVERED, Confidence.HIGH)


def test_season_history_supplies_last_clear_image():
    hist = {RUN - timedelta(days=15): SurfaceClass.DARK}
    s = score_lake(lake, ice(), None, RUN, cfg, s2_history=hist)
    assert (s.label, s.confidence) == (Label.LIKELY_BLACK_ICE, Confidence.MEDIUM)
    assert s.last_clear_day == RUN - timedelta(days=15)
    assert f"dark on {RUN - timedelta(days=15):%b} {(RUN - timedelta(days=15)).day} image" \
        in s.reason


def test_todays_imagery_overrides_history_same_day():
    day = RUN - timedelta(days=1)
    s = score_lake(lake, ice(), img(1, WHITE), RUN, cfg, s2_history={day: SurfaceClass.DARK})
    assert s.label is Label.SNOW_COVERED


# Landsat 8-9 -----------------------------------------------------------------

def ls(days_ago, g, r, sw, temp_c, valid=.9):
    return LSObs(RUN - timedelta(days=days_ago), valid, g, r, sw, temp_c)


def test_classify_ls():
    assert classify_ls(ls(0, .5, .5, .05, -12), cfg) is SurfaceClass.WHITE
    assert classify_ls(ls(0, .1, .09, .01, -6), cfg) is SurfaceClass.DARK
    assert classify_ls(ls(0, .1, .09, .01, 3), cfg) is SurfaceClass.WATER  # above freezing
    assert classify_ls(ls(0, .25, .25, .1, -5), cfg) is SurfaceClass.GREY
    assert classify_ls(ls(0, .1, .09, .01, -6, valid=.5), cfg) is None  # cloudy


def test_ls_snow_threshold_is_its_own():
    # 0.32 is below Sentinel-2's snow brightness but above Landsat's
    assert classify_ls(ls(0, .32, .32, .02, -10), cfg) is SurfaceClass.WHITE


def test_landsat_dark_look_gives_black_ice_and_names_landsat():
    im = ImageryStats((), (), None, (ls(1, .1, .09, .01, -6),))
    sc = score_lake(lake, ice(h=12), im, RUN, cfg)
    assert sc.label is Label.LIKELY_BLACK_ICE
    assert sc.last_clear_day == RUN - timedelta(days=1) and sc.last_clear_sensor == "ls"
    assert "Landsat image" in sc.reason


def test_recent_warm_dark_landsat_look_is_open_water():
    im = ImageryStats((), (), None, (ls(2, .1, .09, .01, 3),))
    sc = score_lake(lake, ice(h=12), im, RUN, cfg)
    assert sc.label is Label.OPEN_WATER
    assert "open water (above freezing)" in sc.reason


def test_old_open_water_look_does_not_block_ice():
    old = {RUN - timedelta(days=30): SurfaceClass.WATER}
    sc = score_lake(lake, ice(h=12), None, RUN, cfg, ls_history=old)
    assert sc.label is not Label.OPEN_WATER


def test_sentinel2_wins_a_day_both_cameras_saw():
    im = ImageryStats((S2Obs(RUN - timedelta(days=1), *WHITE),), (), None,
                      (ls(1, .1, .09, .01, -6),))
    sc = score_lake(lake, ice(h=12), im, RUN, cfg)
    assert sc.label is Label.SNOW_COVERED and sc.last_clear_sensor == "s2"


def test_newer_landsat_look_beats_older_sentinel2():
    im = ImageryStats((S2Obs(RUN - timedelta(days=4), *WHITE),), (), None,
                      (ls(1, .1, .09, .01, -6),))
    sc = score_lake(lake, ice(h=12), im, RUN, cfg)
    assert sc.label is Label.LIKELY_BLACK_ICE and sc.last_clear_sensor == "ls"


def test_valid_ls_classes_and_optical_merge():
    im = ImageryStats((), (), None, (ls(0, .1, .09, .01, -6), ls(1, .1, .09, .01, -6, valid=.1)))
    assert valid_ls_classes(im, cfg) == {D: SurfaceClass.DARK}
    assert optical_classes({D: SurfaceClass.WHITE}, {D: SurfaceClass.DARK,
                                                     D - timedelta(1): SurfaceClass.GREY}) == {
        D: SurfaceClass.WHITE, D - timedelta(1): SurfaceClass.GREY}
