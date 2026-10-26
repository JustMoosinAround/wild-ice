"""Decide which lakes get satellite requests today."""
from __future__ import annotations

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
              cfg: Config, remaining_requests: int) -> list[str]:
    chosen: list[Lake] = []
    for lake in lakes:
        if lake.interior is None:
            continue  # no geometry -> no imagery request possible
        if lake.id in pinned:
            chosen.append(lake)
            continue
        st = ice.get(lake.id)
        if st is None or st.thickness_cm < cfg.ice.open_cm or _snowed_over(st, cfg):
            continue
        chosen.append(lake)
    chosen.sort(key=lambda l: (l.id not in pinned, -l.area_acres))
    ids = [l.id for l in chosen]
    return ids[: max(0, remaining_requests) // 2]  # one S2 + one S1 request per lake
