from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from wildice.config import load_config
from wildice.geo import longest_span_mi, shoreline_index
from wildice.hazards import ridge_note
from wildice.models import DayWeather, IceState, Lake

CFG = load_config(Path(__file__).resolve().parent.parent / "config.yaml")
RUN = date(2026, 11, 13)


def _box(w_deg, h_deg, lon0=-149.5, lat0=61.0):
    return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon0 + w_deg, lat0],
                                                 [lon0 + w_deg, lat0 + h_deg],
                                                 [lon0, lat0 + h_deg], [lon0, lat0]]]}


# ~2.4 mi east-west (0.07 deg lon at 61 N), ~0.4 mi north-south
BIG = Lake("w1", "Big", 600, 0.1, None, 61.0, -149.5, _box(0.07, 0.006), None)
SMALL = Lake("w2", "Small", 40, 0.1, None, 61.0, -149.5, _box(0.01, 0.004), None)
STAR = {"type": "Polygon", "coordinates": [[[0, 0], [4, 1], [5, 5], [6, 1], [10, 0], [6, -1],
                                             [5, -5], [4, -1], [0, 0]]]}


def _ice(cm=8.0):
    return IceState(100, cm, RUN - timedelta(days=10), None, 0.0, None, ())


def _days(means, gust=10.0):
    start = RUN - timedelta(days=len(means) - 1)
    return [DayWeather(start + timedelta(days=i), m - 3, m + 3, m, 0.0, 0.0, gust)
            for i, m in enumerate(means)]


def test_span_and_shape():
    assert longest_span_mi(BIG.interior) == pytest.approx(2.35, rel=0.05)
    assert longest_span_mi(SMALL.interior) < 0.5
    assert shoreline_index(_box(0.01, 0.005)) < 1.3
    assert shoreline_index(STAR) > 1.5


def test_warm_up_after_cold_spell_on_big_lake():
    days = _days([-5, -15, -18, -16, -14, -6, -3, -2])
    note = ridge_note(BIG, days, _ice(), RUN, CFG)
    assert note is not None and "pressure ridges likely" in note and "2.3 mi" in note


def test_no_warning_for_small_lake_steady_cold_or_open_water():
    warm_up = _days([-5, -15, -18, -16, -14, -6, -3, -2])
    assert ridge_note(SMALL, warm_up, _ice(), RUN, CFG) is None
    assert ridge_note(BIG, _days([-12] * 8), _ice(), RUN, CFG) is None
    assert ridge_note(BIG, warm_up, _ice(0.0), RUN, CFG) is None


def test_old_warm_up_has_passed():
    days = _days([-18, -16, -5, -3, -12, -12, -12, -12])  # warmed 5 days ago, cold since
    assert ridge_note(BIG, days, _ice(), RUN, CFG) is None


def test_windy_thaw_warns_ridges_may_be_open():
    days = _days([-10, -10, -10, -10, -10, -10, 2, 3], gust=45.0)
    note = ridge_note(BIG, days, _ice(25.0), RUN, CFG)
    assert note is not None and "open water" in note


def test_points_and_bays_mentioned():
    lake = Lake("w3", "Star", 900, 0.1, None, 61.0, -149.5,
                {"type": "Polygon", "coordinates": [[[-149.5 + x * 0.008, 61.0 + y * 0.002]
                                                     for x, y in STAR["coordinates"][0]]]}, None)
    cfg = replace(CFG, ridges=replace(CFG.ridges, points_index=2.0))
    days = _days([-5, -15, -18, -16, -14, -6, -3, -2])
    note = ridge_note(lake, days, _ice(), RUN, cfg)
    assert note is not None and "points and bays" in note
    assert "points and bays" not in ridge_note(BIG, days, _ice(), RUN, cfg)


def test_big_ice_note_only_on_lakes_over_three_miles():
    from wildice.hazards import big_ice_note
    huge = Lake("w9", "Huge", 9000, 0.1, None, 61.0, -149.5, _box(0.12, 0.01), None)
    calm = _days([-12] * 8)
    note = big_ice_note(huge, calm, _ice(), RUN, CFG)
    assert note is not None and note.startswith("big ice (4.0 mi)") and "windy" not in note
    windy = big_ice_note(huge, _days([-12] * 8, gust=50.0), _ice(), RUN, CFG)
    assert "windy" in windy
    assert big_ice_note(BIG, calm, _ice(), RUN, CFG) is None
    assert big_ice_note(huge, calm, _ice(0.0), RUN, CFG) is None


def _windy_today(gust_today, gust_yesterday=10.0, means=None):
    days = _days(means or [-10] * 8)
    days[-1] = replace(days[-1], gust_kmh=gust_today)
    days[-2] = replace(days[-2], gust_kmh=gust_yesterday)
    return days


def test_lead_risk_today_on_thin_ice_big_sheet():
    from wildice.hazards import lead_note
    note = lead_note(BIG, _windy_today(55.0), _ice(8.0), RUN, CFG)
    assert note is not None and note.startswith("lead risk today: gusts to 55 km/h on ~8 cm ice")


def test_lead_after_yesterdays_wind():
    from wildice.hazards import lead_note
    note = lead_note(BIG, _windy_today(10.0, gust_yesterday=60.0), _ice(8.0), RUN, CFG)
    assert note is not None and "yesterday" in note


def test_no_lead_on_thick_cold_ice_small_lake_or_calm_day():
    from wildice.hazards import lead_note
    assert lead_note(BIG, _windy_today(55.0), _ice(30.0), RUN, CFG) is None
    assert lead_note(SMALL, _windy_today(55.0), _ice(8.0), RUN, CFG) is None
    assert lead_note(BIG, _windy_today(20.0), _ice(8.0), RUN, CFG) is None


def test_thaw_weakened_thick_ice_can_still_lead():
    from wildice.hazards import lead_note
    days = _windy_today(55.0, means=[-10, -10, -10, -10, -10, 1, 2, -1])
    assert lead_note(BIG, days, _ice(30.0), RUN, CFG) is not None


# lakeice.org "Thawed Ice", "New-ice Holes", "Small Ponds"

def _snow_ice(cm, snow, froze_days_ago=10):
    return IceState(100, cm, RUN - timedelta(days=froze_days_ago), None, snow, None, ())


def test_thaw_note_weak_then_rotten_then_recovered():
    from wildice.hazards import thaw_note
    # two days at +5 = 10 thaw degree-days (C), then one cold day: still weak
    weak = thaw_note(SMALL, _days([-10] * 5 + [5, 5, -3]), _ice(20), RUN, CFG)
    assert weak is not None and weak.startswith("thaw-weakened ice: 10 thaw degree-days")
    # 12 days at +5: candled, rotten ice
    rotten = thaw_note(SMALL, _days([-10] * 5 + [5] * 12), _snow_ice(30, 0, 20), RUN, CFG)
    assert rotten.startswith("rotten ice risk: 60 thaw degree-days")
    # three cold days after the thaw: recovered
    assert thaw_note(SMALL, _days([-10] * 5 + [5, 5, -3, -3, -3]), _ice(20), RUN, CFG) is None
    # a small thaw, a snowy warm day, or open water: nothing
    assert thaw_note(SMALL, _days([-10] * 5 + [2, 2]), _ice(20), RUN, CFG) is None
    snowy = [replace(d, snowfall_cm=8.0) if d.t_mean > 0 else d for d in _days([-10] * 5 + [5, 5])]
    assert thaw_note(SMALL, snowy, _ice(20), RUN, CFG) is None
    assert thaw_note(SMALL, _days([-10] * 5 + [5, 5]), _ice(0.0), RUN, CFG) is None


def test_thaw_note_counts_only_since_freeze_up_and_names_shallow_ponds():
    from wildice.hazards import thaw_note
    days = _days([5, 5, 5, -10, -10])  # the thaw came before this ice formed
    assert thaw_note(SMALL, days, _snow_ice(5, 0, froze_days_ago=1), RUN, CFG) is None
    pond = replace(SMALL, depth_m=1.0)
    note = thaw_note(pond, _days([-10] * 5 + [5, 5]), _ice(20), RUN, CFG)
    assert "shallow" in note


def test_new_ice_note_for_the_first_week():
    from wildice.hazards import new_ice_note
    assert "skinned-over holes" in new_ice_note(_snow_ice(6, 0, froze_days_ago=3), RUN, CFG)
    assert new_ice_note(_snow_ice(6, 0, froze_days_ago=8), RUN, CFG) is None
    assert new_ice_note(_snow_ice(0.0, 0, froze_days_ago=3), RUN, CFG) is None


def test_slush_note_when_snow_outweighs_the_ice():
    from wildice.hazards import slush_note
    assert slush_note(_snow_ice(10, 4), CFG) is None
    note = slush_note(_snow_ice(10, 8), CFG)
    assert note.startswith("8 cm of snow on ~10 cm ice")
    assert slush_note(_snow_ice(10, 1.5), CFG) is None   # under cover_cm


def test_big_ice_wants_thicker_ice():
    from wildice.hazards import big_ice_note
    huge = Lake("w9", "Huge", 9000, 0.1, None, 61.0, -149.5, _box(0.12, 0.01), None)
    assert "5 cm more ice" in big_ice_note(huge, _days([-12] * 8), _ice(), RUN, CFG)
