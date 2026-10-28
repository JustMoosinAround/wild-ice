"""Decide which lakes get satellite requests today."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from wildice.config import Config
from wildice.models import IceState, Lake


def _snowed_over(st: IceState, cfg: Config) -> bool:
    if st.snow_since_reset_cm <= cfg.snow.cover_cm:
        return False
    after = st.last_snow_day
    if after is None:
        return True
    if st.last_reset is not None and st.last_reset.day > after:
        return False
    return not any(r.day > after for r in st.possible_resets)


def shortlist(lakes: list[Lake], ice: dict[str, IceState], pinned: frozenset[str],
              cfg: Config, remaining_requests: int,
              hidden: frozenset[str] = frozenset(),
              last_checked: Mapping[str, date] | None = None) -> list[str]:
    """Lake ids to image today, best first, within `remaining_requests` (today's share).

    Order: pinned lakes, then lakes the weather says are clear of snow (largest
    first), then snowed-over lakes, least recently checked first. Snowed-over
    lakes stay in the rotation because wind can sweep them clear, and only a
    satellite image shows that.
    """
    checked = last_checked or {}
    ranked: list[tuple[tuple, str]] = []
    for lake in lakes:
        if lake.interior is None:
            continue  # no geometry -> no imagery request possible
        if lake.id in hidden:
            continue  # the owner hid it: not worth a request
        st = ice.get(lake.id)
        if lake.id in pinned:
            ranked.append(((0, date.min, -lake.area_acres), lake.id))
            continue
        if st is None or st.thickness_cm < cfg.ice.open_cm:
            continue
        if _snowed_over(st, cfg):
            ranked.append(((2, checked.get(lake.id, date.min), -lake.area_acres), lake.id))
        else:
            ranked.append(((1, date.min, -lake.area_acres), lake.id))
    ranked.sort()
    ids = [lake_id for _, lake_id in ranked]
    return ids[: max(0, remaining_requests) // 2]  # one S2 + one S1 request per lake
