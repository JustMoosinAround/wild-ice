from datetime import date, timedelta
from pathlib import Path

from wildice.config import load_config
from wildice.models import (
    Confidence, IceState, ImageryStats, Label, Lake, ResetEvent, ResetKind, S1Obs, S2Obs,
    SurfaceClass,
)
from wildice.score import classify_s2, s1_frozen, score_lake, valid_s2_classes

cfg = load_config(Path("config.yaml"))
RUN = date(2026, 1, 10)
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
    assert "radar shows ice" in s.reason


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
    assert "no snow since rain/thaw on Jan 2" in s.reason


def test_reason_dates_have_no_leading_zero():
    im = ImageryStats((S2Obs(date(2026, 1, 5), *DARK),), (), None)
    s = score_lake(lake, ice(), im, date(2026, 1, 6), cfg)
    assert "dark on Jan 5 image" in s.reason


def test_reason_snow_part():
    r = ResetEvent(date(2026, 1, 2), ResetKind.FREEZE_UP)
    s = score_lake(lake, ice(snow=4, reset=r, last_snow=RUN), None, RUN, cfg)
    assert "4 cm snow since Jan 2" in s.reason


def test_reason_mentions_possible_reset():
    pr = ResetEvent(date(2026, 11, 6), ResetKind.POSSIBLE)
    s = score_lake(lake, ice(possible=[pr]), None, date(2026, 11, 10), cfg)
    assert "possible wind clearing Nov 6" in s.reason
