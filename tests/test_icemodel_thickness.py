from datetime import date, timedelta
from pathlib import Path

import pytest

from wildice.config import load_config
from wildice.icemodel import run_ice_model
from wildice.models import DayWeather, ResetEvent, ResetKind

cfg = load_config(Path("config.yaml"))


def wx(day_offset, t_mean, snow=0.0, rain=0.0, gust=0.0):
    return DayWeather(day=date(2025, 11, 1) + timedelta(day_offset), t_min=t_mean - 3,
                      t_max=t_mean + 3, t_mean=t_mean, snowfall_cm=snow, rain_mm=rain,
                      gust_kmh=gust)


def test_cold_week_thickness():
    s = run_ice_model([wx(i, -5) for i in range(7)], cfg)
    assert s.cum_fdd == 35
    assert s.thickness_cm == pytest.approx(11.83, abs=0.01)


def test_thaw_subtracts_mean():
    s = run_ice_model([wx(i, -5) for i in range(5)] + [wx(5, 3)], cfg)
    assert s.cum_fdd == 22
    assert s.thickness_cm == pytest.approx(9.38, abs=0.01)


def test_never_negative():
    s = run_ice_model([wx(i, 4) for i in range(4)], cfg)
    assert s.cum_fdd == 0 and s.thickness_cm == 0 and s.freeze_up is None


def test_freeze_up_is_first_reset():
    s = run_ice_model([wx(0, 1), wx(1, -2)], cfg)
    assert s.freeze_up == date(2025, 11, 2)
    assert s.last_reset == ResetEvent(date(2025, 11, 2), ResetKind.FREEZE_UP)


def test_full_melt_then_new_freeze_up():
    s = run_ice_model([wx(0, -2), wx(1, 3), wx(2, -1)], cfg)
    assert s.freeze_up == date(2025, 11, 3)


def test_empty_days():
    s = run_ice_model([], cfg)
    assert s.thickness_cm == 0 and s.freeze_up is None
