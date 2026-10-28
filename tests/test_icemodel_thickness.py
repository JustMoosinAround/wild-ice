from datetime import date, timedelta
from pathlib import Path

import pytest

from wildice.config import load_config
from wildice.icemodel import ashton_thickness_cm, run_ice_model
from wildice.models import DayWeather, ResetEvent, ResetKind

cfg = load_config(Path("config.yaml"))


def wx(day_offset, t_mean, snow=0.0, rain=0.0, gust=0.0):
    return DayWeather(day=date(2025, 11, 1) + timedelta(day_offset), t_min=t_mean - 3,
                      t_max=t_mean + 3, t_mean=t_mean, snowfall_cm=snow, rain_mm=rain,
                      gust_kmh=gust)


def test_cold_week_thickness():
    s = run_ice_model([wx(i, -5) for i in range(7)], cfg)
    assert s.cum_fdd == 35
    assert s.thickness_cm == pytest.approx(12.63, abs=0.01)  # Ashton (1989), H = 20


def test_thaw_subtracts_mean():
    s = run_ice_model([wx(i, -5) for i in range(5)] + [wx(5, 3)], cfg)
    assert s.cum_fdd == 22
    assert s.thickness_cm == pytest.approx(8.89, abs=0.01)


def test_never_negative():
    s = run_ice_model([wx(i, 4) for i in range(4)], cfg)
    assert s.cum_fdd == 0 and s.thickness_cm == 0 and s.freeze_up is None


def test_freeze_up_is_first_reset():
    s = run_ice_model([wx(0, 1), wx(1, -5)], cfg)  # 5 degC-days -> 2.5 cm, caught
    assert s.freeze_up == date(2025, 11, 2)
    assert s.last_reset == ResetEvent(date(2025, 11, 2), ResetKind.FREEZE_UP)


def test_full_melt_then_new_freeze_up():
    s = run_ice_model([wx(0, -5), wx(1, 6), wx(2, -5)], cfg)
    assert s.freeze_up == date(2025, 11, 3)


def test_empty_days():
    s = run_ice_model([], cfg)
    assert s.thickness_cm == 0 and s.freeze_up is None


@pytest.mark.parametrize("fdd, cm", [(0, 0.0), (2, 1.08), (5, 2.53), (35, 12.63), (100, 26.07)])
def test_ashton_thickness(fdd, cm):
    assert ashton_thickness_cm(fdd, cfg.ice.ashton_h) == pytest.approx(cm, abs=0.01)


def test_thin_ice_grows_slower_than_stefan_said():
    # One barely-freezing day must not count as real ice (the Ewan Lake bug).
    s = run_ice_model([wx(0, -0.4)], cfg)
    assert s.thickness_cm < 0.5 and s.freeze_up is None


def test_lake_catches_only_at_open_cm():
    days = [wx(i, -1) for i in range(3)]       # 3 degC-days -> ~1.5 cm, not caught
    assert run_ice_model(days, cfg).freeze_up is None
    days.append(wx(3, -1))                     # 4 degC-days -> ~2.06 cm, caught
    assert run_ice_model(days, cfg).freeze_up == date(2025, 11, 4)


def test_snow_before_catch_is_not_counted():
    # Snow on open water or skim ice melts; only snow after the lake catches counts.
    days = [wx(0, -0.5), wx(1, -0.5, snow=15), wx(2, -8), wx(3, -8, snow=1)]
    s = run_ice_model(days, cfg)
    assert s.freeze_up == date(2025, 11, 3)
    assert s.snow_since_reset_cm == pytest.approx(1.0)


def test_ewan_lake_october_2026():
    """Real Open-Meteo daily means and snowfall for Ewan Lake's cell, Oct 16-28 2026."""
    temps = [-0.4, -0.4, -0.9, 0.2, -0.3, -4.1, -8.3, -11.7, -8.6, -2.8, -2.6, -6.2, -6.7]
    snow = [0.6, 0, 0, 6.7, 15.4, 0.2, 0, 0, 0, 1.2, 0.3, 0, 0]
    start = date(2026, 10, 16)
    days = [DayWeather(start + timedelta(i), t - 3, t + 3, t, sn, 0.0, 20.0)
            for i, (t, sn) in enumerate(zip(temps, snow))]
    s = run_ice_model(days, cfg)
    assert s.freeze_up == date(2026, 10, 21)
    assert s.snow_since_reset_cm == pytest.approx(1.7)    # Oct 21 onward; was 24.5 cm
    assert s.snow_since_reset_cm <= cfg.snow.cover_cm     # so not "snow-covered"
