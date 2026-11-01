"""Ice thickness, freeze-up, snow counter and reset detection."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from math import log10, sqrt

from wildice.config import Config
from wildice.models import DayWeather, IceState, ResetEvent, ResetKind, SurfaceClass


# Ice properties for Ashton's thin-ice growth formula.
_K_ICE = 2.24          # thermal conductivity of ice, W/m/K
_RHO_ICE = 917.0       # density of ice, kg/m^3
_LATENT = 334000.0     # latent heat of fusion, J/kg
_SECONDS_PER_DAY = 86400

# Water temperature trails the air: each day it closes 1/lag of the gap. Fitted on
# AKTEMP lake loggers (21 fall seasons, 0.2-0.7 C error): lag ~ 17 days for a few
# hundred acres, ~ 40 for several thousand. Small lakes are shallow, so they track
# the air within days.
_LAG_A, _LAG_B = -18.0, 15.0     # lag days = A + B * log10(acres)
_LAG_MIN, _LAG_MAX = 5.0, 50.0
# Above 4 C the whole lake mixes and cools slowly; below it the cold water stays on
# top, so the surface finishes cooling to 0 C about four times faster.
_MIXED_C = 4.0
_SURFACE_SPEEDUP = 4.0
_SURFACE_LAG_MIN = 2.0

TraceRow = tuple[date, float, float]  # day, water C, ice cm


def ashton_thickness_cm(fdd: float, h: float) -> float:
    """Ice thickness (cm) after `fdd` freezing degree-days (Ashton 1989, Water Resources
    Research 25(3)). Unlike Stefan's sqrt rule it accounts for the air's limited ability
    to carry heat away, so thin ice grows slowly: h = -k/H + sqrt((k/H)^2 + 2 k FDD / (rho L)).
    """
    if fdd <= 0:
        return 0.0
    a = _K_ICE / h
    b = 2 * _K_ICE * fdd * _SECONDS_PER_DAY / (_RHO_ICE * _LATENT)
    return max(0.0, (-a + sqrt(a * a + b)) * 100)


def water_lag_days(area_acres: float) -> float:
    """Days the lake's water takes to close most of the gap to the air temperature."""
    lag = _LAG_A + _LAG_B * log10(max(area_acres, 1.0))
    return min(_LAG_MAX, max(_LAG_MIN, lag))


def _mmdd(text: str) -> tuple[int, int]:
    month, day = (int(x) for x in text.split("-"))
    return month, day


def in_low_sun(day: date, cfg: Config) -> bool:
    """True if `day` falls in the configured low-sun window (inclusive; may wrap the year)."""
    start, end = _mmdd(cfg.imagery.low_sun_start), _mmdd(cfg.imagery.low_sun_end)
    md = (day.month, day.day)
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end


def run_ice_model(
    days: Sequence[DayWeather],
    cfg: Config,
    s2_classes: Mapping[date, SurfaceClass] | None = None,
    area_acres: float | None = None,
    trace: list[TraceRow] | None = None,
) -> IceState:
    """Run the model day by day over a season-to-date, ascending list of days.

    With `area_acres`, ice cannot start until the lake's water has cooled to 0 C (see
    `water_lag_days`); without it the water is taken as already at 0 C. Each day's
    water temperature and ice thickness are appended to `trace` if given.
    """
    cum = 0.0
    lag = water_lag_days(area_acres) if area_acres is not None else None
    water = cfg.ice.water_start_c if lag is not None else 0.0
    thickness = 0.0
    freeze_up: date | None = None
    last_reset: ResetEvent | None = None
    snow_cm = 0.0
    last_snow_day: date | None = None
    possible: list[ResetEvent] = []
    seen_white = False
    warm_days = 0  # length of the current consecutive warm (t_mean > 0) run
    warm_rain = 0.0  # total rain over the current warm run
    prev_warm_days = 0  # the run that ended on the previous day
    prev_warm_rain = 0.0
    s2_classes = s2_classes or {}
    r = cfg.reset

    for d in days:
        # track warm runs (independent of frozen state)
        if d.t_mean > 0:
            warm_days += 1
            warm_rain += d.rain_mm
            prev_warm_days, prev_warm_rain = 0, 0.0
        else:
            prev_warm_days, prev_warm_rain = warm_days, warm_rain
            warm_days, warm_rain = 0, 0.0

        # 1. water temperature, thickness / freeze-up
        if cum > 0 or lag is None:
            cum = max(0.0, cum - d.t_mean)  # ice (or no water model): water held at 0 C
            water = 0.0
        else:
            step = lag if water > _MIXED_C else max(_SURFACE_LAG_MIN, lag / _SURFACE_SPEEDUP)
            water = max(0.0, water + (d.t_mean - water) / step)
            if water == 0.0:
                cum = max(0.0, -d.t_mean)  # cooled to 0 C today: ice can start
        thickness = ashton_thickness_cm(cum, cfg.ice.ashton_h)
        # The lake "catches" once the ice reaches open_cm; before that, snow lands in
        # open water or on skim ice and melts, so nothing is tracked yet. It stays caught
        # until the ice is gone entirely.
        was_caught = freeze_up is not None
        frozen = thickness > 0 and (was_caught or thickness >= cfg.ice.open_cm)
        just_froze = frozen and not was_caught
        if just_froze:
            freeze_up = d.day
            last_reset = ResetEvent(d.day, ResetKind.FREEZE_UP)
            snow_cm = 0.0
            possible = []
            seen_white = False
        elif not frozen and was_caught:
            # full melt: back to open water, nothing left to track
            freeze_up = None
            last_reset = None
            snow_cm = 0.0
            possible = []
            seen_white = False

        if frozen:
            # 2. resets, strongest evidence first
            surface = s2_classes.get(d.day)
            if surface == SurfaceClass.WHITE:
                seen_white = True
            reset_kind: ResetKind | None = None
            # low sun makes snow look dark, so a dark image then proves nothing
            if surface == SurfaceClass.DARK and not in_low_sun(d.day, cfg) and (
                snow_cm > cfg.snow.cover_cm
                or seen_white
                or (last_reset is not None and last_reset.kind == ResetKind.LIKELY)
            ):
                reset_kind = ResetKind.CONFIRMED
            elif (
                not just_froze
                and d.t_mean <= 0
                and prev_warm_days > 0
                and (prev_warm_days >= r.thaw_days or prev_warm_rain >= r.rain_mm)
            ):
                reset_kind = ResetKind.LIKELY
            if reset_kind is not None:
                last_reset = ResetEvent(d.day, reset_kind)
                snow_cm = 0.0
                possible = []
                seen_white = False
            elif d.gust_kmh >= r.wind_gust_kmh and 0 < snow_cm <= r.light_snow_cm:
                possible.append(ResetEvent(d.day, ResetKind.POSSIBLE))

            # 3. snow counter
            if d.snowfall_cm > 0:
                snow_cm += d.snowfall_cm
                last_snow_day = d.day

        if trace is not None:
            trace.append((d.day, water, thickness))

    return IceState(
        cum_fdd=cum,
        thickness_cm=thickness,
        freeze_up=freeze_up,
        last_reset=last_reset,
        snow_since_reset_cm=snow_cm,
        last_snow_day=last_snow_day,
        possible_resets=tuple(possible),
        water_c=water,
    )
