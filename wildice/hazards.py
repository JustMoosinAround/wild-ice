"""Hazard notes from lake size, shape and recent weather (lakeice.org).

Pressure ridges:

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
    note = (f"big ice ({span:.1f} mi): expect leads, open areas and thinly refrozen leads; "
            "want 5 cm more ice than on a small pond")
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


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"


def thaw_degree_days(days: Sequence[DayWeather], since: date | None, run_date: date,
                     cfg: Config) -> float:
    """Thaw degree-days (C) since the ice last had `recover_days` cold days in a row,
    counting only days after `since` (freeze-up). Warm days that snowed don't count."""
    t = cfg.thaw
    start = run_date - timedelta(days=t.lookback_days - 1)
    if since is not None:
        start = max(start, since)
    total, cold_run = 0.0, 0
    for d in sorted((d for d in days if start <= d.day <= run_date),
                    key=lambda d: d.day, reverse=True):
        if d.t_mean < 0:
            cold_run += 1
            if cold_run >= t.recover_days:
                break
            continue
        cold_run = 0
        if d.t_mean > 0 and d.snowfall_cm < cfg.snow.cover_cm:
            total += d.t_mean
    return total


def thaw_note(lake: Lake, days: Sequence[DayWeather], ice: IceState, run_date: date,
              cfg: Config) -> str | None:
    """lakeice.org "Thawed Ice": more people go through thaw-weakened ice than thin cold
    ice. ~15 thaw degree-days F (8 C) with some wind fill a sheet with holes and hide
    old hazards; ~100 F (57 C) rotted 13.5" candled ice past holding a person. The ice
    recovers after a few cold days. Shallow ponds thin fastest, at the edges first."""
    t = cfg.thaw
    if ice.thickness_cm < cfg.ice.open_cm:
        return None
    tdd = thaw_degree_days(days, ice.freeze_up, run_date, cfg)
    if tdd < t.weak_cdd:
        return None
    if tdd >= t.rotten_cdd:
        note = (f"rotten ice risk: {tdd:.0f} thaw degree-days (C) since the last cold spell; "
                "thawed ice can fail at any thickness")
    else:
        note = (f"thaw-weakened ice: {tdd:.0f} thaw degree-days (C) since the last cold spell; "
                "expect holes and soft spots, and thickness overstates strength "
                f"until {t.recover_days} cold days")
    if lake.depth_m is not None and lake.depth_m < t.shallow_m:
        note += "; shallow pond: the edges and weedy shallows go first"
    return note


def new_ice_note(ice: IceState, run_date: date, cfg: Config) -> str | None:
    """lakeice.org "New-ice Holes": a bit under half of new sheets have holes that stay
    open for hours to a week, then skin over; new ice also varies in thickness."""
    if ice.thickness_cm < cfg.ice.open_cm or ice.freeze_up is None:
        return None
    if (run_date - ice.freeze_up).days >= cfg.thaw.new_ice_days:
        return None
    return (f"new ice (froze about {_fmt(ice.freeze_up)}): thin spots and skinned-over holes "
            "are common in the first week")


def slush_note(ice: IceState, cfg: Config) -> str | None:
    """lakeice.org "Small Ponds": snow deeper than about half the ice thickness pushes
    the ice under water, which floods up through cracks into slush under the snow."""
    snow = ice.snow_since_reset_cm
    if ice.thickness_cm < cfg.ice.open_cm or snow <= cfg.snow.cover_cm:
        return None
    if snow <= cfg.thaw.slush_ratio * ice.thickness_cm:
        return None
    return (f"{snow:.0f} cm of snow on ~{ice.thickness_cm:.0f} cm ice: heavy enough to flood it, "
            "expect slush under the snow")
