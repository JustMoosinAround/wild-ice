"""Ice thickness, freeze-up, snow counter and reset detection."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from math import sqrt

from wildice.config import Config
from wildice.models import DayWeather, IceState, ResetEvent, ResetKind, SurfaceClass


def run_ice_model(
    days: Sequence[DayWeather],
    cfg: Config,
    s2_classes: Mapping[date, SurfaceClass] | None = None,
) -> IceState:
    """Run the model day by day over a season-to-date, ascending list of days."""
    cum = 0.0
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

        # 1. thickness / freeze-up
        cum = max(0.0, cum - d.t_mean)
        prev_thickness = thickness
        thickness = cfg.ice.alpha * sqrt(cum)
        frozen = thickness > 0
        just_froze = frozen and prev_thickness == 0
        if frozen and prev_thickness == 0:
            freeze_up = d.day
            last_reset = ResetEvent(d.day, ResetKind.FREEZE_UP)
            snow_cm = 0.0
            possible = []
            seen_white = False
        elif not frozen and prev_thickness > 0:
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
            if surface == SurfaceClass.DARK and (
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

    return IceState(
        cum_fdd=cum,
        thickness_cm=thickness,
        freeze_up=freeze_up,
        last_reset=last_reset,
        snow_since_reset_cm=snow_cm,
        last_snow_day=last_snow_day,
        possible_resets=tuple(possible),
    )
