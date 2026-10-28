from datetime import date, timedelta
from pathlib import Path

import pytest

from wildice.config import load_config
from wildice.icemodel import run_ice_model
from wildice.models import DayWeather, ResetEvent, ResetKind, SurfaceClass

cfg = load_config(Path("config.yaml"))


def wx(day_offset, t_mean, snow=0.0, rain=0.0, gust=0.0):
    return DayWeather(day=date(2025, 11, 1) + timedelta(day_offset), t_min=t_mean - 3,
                      t_max=t_mean + 3, t_mean=t_mean, snowfall_cm=snow, rain_mm=rain,
                      gust_kmh=gust)


def d(offset):
    return date(2025, 11, 1) + timedelta(offset)


def cold(snow=None, gust=None, n=10):
    """n cold days at -5 with optional {offset: value} overrides."""
    snow, gust = snow or {}, gust or {}
    return [wx(i, -5, snow=snow.get(i, 0.0), gust=gust.get(i, 0.0)) for i in range(n)]


def test_snow_accumulates_after_freeze_up():
    s = run_ice_model(cold(snow={3: 1.5, 5: 1.0}), cfg)
    assert s.snow_since_reset_cm == pytest.approx(2.5)
    assert s.last_snow_day == date(2025, 11, 6)


def test_snow_before_freeze_up_ignored():
    days = [wx(0, 2, snow=4)] + [wx(i, -5) for i in range(1, 11)]
    s = run_ice_model(days, cfg)
    assert s.snow_since_reset_cm == 0


def test_rain_then_refreeze_is_likely_reset():
    days = [wx(i, -5, snow=3 if i == 3 else 0) for i in range(5)]
    days += [wx(5, 1, rain=6), wx(6, -3)]
    s = run_ice_model(days, cfg)
    assert s.last_reset == ResetEvent(date(2025, 11, 7), ResetKind.LIKELY)
    assert s.snow_since_reset_cm == 0


def test_two_thaw_days_then_refreeze_is_likely_reset():
    days = cold(n=5) + [wx(5, 1), wx(6, 1), wx(7, -3)]
    s = run_ice_model(days, cfg)
    assert s.last_reset.kind == ResetKind.LIKELY


def test_one_dry_warm_day_is_not_reset():
    days = cold(n=5) + [wx(5, 1), wx(6, -3)]
    s = run_ice_model(days, cfg)
    assert s.last_reset.kind == ResetKind.FREEZE_UP


def test_wind_after_light_snow_is_possible():
    s = run_ice_model(cold(snow={3: 3}, gust={5: 70}), cfg)
    assert s.possible_resets == (ResetEvent(date(2025, 11, 6), ResetKind.POSSIBLE),)
    assert s.snow_since_reset_cm == 3


def test_wind_after_heavy_snow_is_not_possible():
    s = run_ice_model(cold(snow={3: 8}, gust={5: 70}), cfg)
    assert s.possible_resets == ()


def test_dark_image_after_snow_confirms_reset():
    s = run_ice_model(cold(snow={3: 3}), cfg, {d(5): SurfaceClass.DARK})
    assert s.last_reset == ResetEvent(date(2025, 11, 6), ResetKind.CONFIRMED)
    assert s.snow_since_reset_cm == 0


def test_dark_image_without_prior_snow_is_not_reset():
    s = run_ice_model(cold(), cfg, {d(5): SurfaceClass.DARK})
    assert s.last_reset.kind == ResetKind.FREEZE_UP


def test_white_then_dark_confirms_reset():
    s = run_ice_model(cold(), cfg, {d(4): SurfaceClass.WHITE, d(6): SurfaceClass.DARK})
    assert s.last_reset.kind == ResetKind.CONFIRMED


def test_dark_after_likely_reset_upgrades_to_confirmed():
    days = cold(n=5) + [wx(5, 1), wx(6, 1), wx(7, -3), wx(8, -5), wx(9, -5)]
    s = run_ice_model(days, cfg, {d(9): SurfaceClass.DARK})
    assert s.last_reset == ResetEvent(d(9), ResetKind.CONFIRMED)


def test_reset_clears_possible_and_white_flag():
    # possible on day 5, then confirmed dark day 6 clears it; later dark needs new evidence
    s = run_ice_model(cold(snow={3: 3}, gust={5: 70}), cfg,
                      {d(6): SurfaceClass.DARK})
    assert s.possible_resets == ()
    s = run_ice_model(cold(), cfg, {d(2): SurfaceClass.WHITE, d(3): SurfaceClass.DARK,
                                    d(5): SurfaceClass.DARK})
    assert s.last_reset == ResetEvent(d(3), ResetKind.CONFIRMED)


def test_freeze_up_after_warm_run_is_not_likely_reset():
    s = run_ice_model([wx(0, 1), wx(1, 1), wx(2, -5)], cfg)
    assert s.last_reset == ResetEvent(date(2025, 11, 3), ResetKind.FREEZE_UP)


def test_freeze_up_after_rain_is_not_likely_reset():
    s = run_ice_model([wx(0, 1, rain=6), wx(1, -5)], cfg)
    assert s.last_reset == ResetEvent(date(2025, 11, 2), ResetKind.FREEZE_UP)


def _cold_from(start, n, snow=None):
    snow = snow or {}
    return [DayWeather(start + timedelta(i), -8, -2, -5, snow.get(i, 0.0), 0.0, 0.0)
            for i in range(n)]


def test_low_sun_dark_does_not_confirm_reset():
    start = date(2025, 11, 20)  # Dec 1 (offset 11) is inside the low-sun window
    s = run_ice_model(_cold_from(start, 20, snow={5: 3}), cfg,
                      {date(2025, 12, 1): SurfaceClass.DARK})
    assert s.last_reset.kind == ResetKind.FREEZE_UP
    assert s.snow_since_reset_cm == 3


def test_dark_just_outside_low_sun_still_confirms():
    start = date(2025, 11, 10)
    s = run_ice_model(_cold_from(start, 15, snow={3: 3}), cfg,
                      {date(2025, 11, 24): SurfaceClass.DARK})
    assert s.last_reset == ResetEvent(date(2025, 11, 24), ResetKind.CONFIRMED)


def test_low_sun_white_still_counts_for_later_dark():
    start = date(2026, 1, 1)
    s = run_ice_model(_cold_from(start, 25), cfg,
                      {date(2026, 1, 10): SurfaceClass.WHITE,
                       date(2026, 1, 20): SurfaceClass.DARK})
    assert s.last_reset == ResetEvent(date(2026, 1, 20), ResetKind.CONFIRMED)


def test_in_low_sun_helper():
    from wildice.icemodel import in_low_sun
    assert in_low_sun(date(2025, 12, 25), cfg) and in_low_sun(date(2026, 1, 15), cfg)
    assert not in_low_sun(date(2026, 1, 16), cfg) and not in_low_sun(date(2025, 11, 24), cfg)
