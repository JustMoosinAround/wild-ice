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

    for d in days:
        # 1. thickness / freeze-up
        cum = max(0.0, cum - d.t_mean)
        prev_thickness = thickness
        thickness = cfg.ice.alpha * sqrt(cum)
        frozen = thickness > 0
        if frozen and prev_thickness == 0:
            freeze_up = d.day
            last_reset = ResetEvent(d.day, ResetKind.FREEZE_UP)
            snow_cm = 0.0
            possible = []
        elif not frozen and prev_thickness > 0:
            # full melt: back to open water, nothing left to track
            freeze_up = None
            last_reset = None
            snow_cm = 0.0
            possible = []

        if frozen:
            # 2. resets (task 3)
            # 3. snow counter (task 3)
            pass

    return IceState(
        cum_fdd=cum,
        thickness_cm=thickness,
        freeze_up=freeze_up,
        last_reset=last_reset,
        snow_since_reset_cm=snow_cm,
        last_snow_day=last_snow_day,
        possible_resets=tuple(possible),
    )
