"""Pressure-ridge warnings from lake size, shape and recent weather.

From lakeice.org (Pressure Ridges, Pressure Ridges - More): ridges form on ice sheets
about a mile or more across, mostly while the ice is 2-4" thick, when a cold spell
ends and the warming ice expands against the shore. They run between points of land
and across bay mouths; round lakes with gentle shores get fewer. Warm windy thaws
melt ridges into lines of open water.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from wildice.config import Config
from wildice.geo import longest_span_mi, shoreline_index
from wildice.models import DayWeather, IceState, Lake

LOOKBACK_DAYS = 8  # how far back to find the cold spell


def ridge_note(lake: Lake, days: Sequence[DayWeather], ice: IceState, run_date: date,
               cfg: Config) -> str | None:
    r = cfg.ridges
    if lake.interior is None or ice.thickness_cm < cfg.ice.open_cm:
        return None
    span = longest_span_mi(lake.interior)
    if span < r.min_span_mi:
        return None
    recent_from = run_date - timedelta(days=r.window_days - 1)
    past = [d for d in days if run_date - timedelta(days=LOOKBACK_DAYS - 1) <= d.day <= run_date]
    if not past:
        return None
    notes = []
    coldest = min(past, key=lambda d: d.t_mean)
    after = [d for d in past if d.day > coldest.day and d.day >= recent_from]
    if after and max(d.t_mean for d in after) - coldest.t_mean >= r.warmup_c:
        notes.append(f"pressure ridges likely after the warm-up (lake {span:.1f} mi across)")
    thaw = [d for d in past if d.day >= recent_from and d.t_mean > 0 and d.gust_kmh >= r.thaw_gust_kmh]
    if thaw:
        notes.append("windy thaw: ridges and cracks may be open water")
    if not notes:
        return None
    if shoreline_index(lake.interior) >= r.points_index:
        notes.append("many points and bays: expect ridges off points and across bay mouths")
    return "; ".join(notes)


def big_ice_note(lake: Lake, days: Sequence[DayWeather], ice: IceState, run_date: date,
                 cfg: Config) -> str | None:
    """lakeice.org "Big Ice": past a few miles, wind and currents make leads, open areas
    and refrozen leads common, and strong wind can move whole sheets."""
    r = cfg.ridges
    if lake.interior is None or ice.thickness_cm < cfg.ice.open_cm:
        return None
    span = longest_span_mi(lake.interior)
    if span < r.big_ice_mi:
        return None
    note = f"big ice ({span:.1f} mi): expect leads, open areas and thinly refrozen leads"
    recent_from = run_date - timedelta(days=r.window_days - 1)
    if any(recent_from <= d.day <= run_date and d.gust_kmh >= r.thaw_gust_kmh for d in days):
        note += "; windy: sheets can shift and open new leads"
    return note


def lead_note(lake: Lake, days: Sequence[DayWeather], ice: IceState, run_date: date,
              cfg: Config) -> str | None:
    """lakeice.org "Leads": strong wind (~30 mph) splits sheets a couple of miles across,
    most easily when ice is thin (~4") or thaw-weakened; the gap can open between
    skaters and shore in minutes, and takes days of cold to refreeze."""
    r = cfg.ridges
    if lake.interior is None or ice.thickness_cm < cfg.ice.open_cm:
        return None
    span = longest_span_mi(lake.interior)
    if span < r.lead_min_span_mi:
        return None
    by_day = {d.day: d for d in days}
    thawed = any(run_date - timedelta(days=r.window_days - 1) <= d.day <= run_date
                 and d.t_mean > 0 for d in days)
    if ice.thickness_cm > r.lead_max_cm and not thawed:
        return None
    today, yesterday = by_day.get(run_date), by_day.get(run_date - timedelta(days=1))
    weak = f"~{ice.thickness_cm:.0f} cm" + (" thaw-weakened" if thawed else "")
    if today is not None and today.gust_kmh >= r.lead_gust_kmh:
        return (f"lead risk today: gusts to {today.gust_kmh:.0f} km/h on {weak} ice; "
                "the sheet can split between you and shore")
    if yesterday is not None and yesterday.gust_kmh >= r.lead_gust_kmh:
        return "strong wind yesterday: new leads may be open or only thinly refrozen"
    return None
