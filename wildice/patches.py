"""Patchy lakes: grey ice next to black patches, and patches that later even out.

lakeice.org (Ice Sheet Edges, Polynyas): lakes freeze in stages, so thick older ice
(grey on Sentinel-2 once cracks and dust catch snow) can border open water or much
thinner new black ice. Open patches (polynyas) freeze over "fitfully", with thin
spots, and their outline can last for weeks. A dark lake that looks patchy is not
evidence that the black part is safe; a patch that evens out is newer ice there.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, timedelta

from wildice.config import Config
from wildice.icemodel import run_ice_model
from wildice.models import Confidence, DayWeather, ImageryStats, Label, Score
from wildice.score import classify_s2

_CONF_ORDER = (Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH)


def _cap(conf: Confidence, at: Confidence) -> Confidence:
    return conf if _CONF_ORDER.index(conf) <= _CONF_ORDER.index(at) else at


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"


def texture_by_day(history: Mapping[date, float] | None, imagery: ImageryStats | None,
                   cfg: Config) -> dict[date, float]:
    """Saved texture by day plus today's clear Sentinel-2 looks that came with one."""
    out = dict(history or {})
    for obs in (imagery.s2 if imagery else ()):
        if obs.texture is not None and classify_s2(obs, cfg) is not None:
            out[obs.day] = obs.texture
    return out


def apply_patches(score: Score, texture: Mapping[date, float], days: Sequence[DayWeather],
                  run_date: date, cfg: Config) -> Score:
    t = cfg.imagery.patchy_texture
    since = run_date - timedelta(days=cfg.imagery.patch_days)
    patchy = [d for d, v in texture.items() if v >= t and since <= d <= run_date]
    if not patchy:
        return score
    p = max(patchy)
    evened = [d for d, v in texture.items() if p < d <= run_date and v < t]
    label, conf = score.label, _cap(score.confidence, Confidence.MEDIUM)
    if not evened:
        note = (f"patchy on {_fmt(p)} image: grey ice with black patches "
                "(open water or newer, thinner ice)")
    else:
        # the black part may have been open water when seen: grow new ice from then
        new_cm = run_ice_model([d for d in days if p < d.day <= run_date], cfg).thickness_cm
        note = f"black patch seen {_fmt(p)} has evened out: newer ice there, ~{new_cm:.0f} cm"
        if new_cm < cfg.ice.skate_cm and label in (Label.LIKELY_BLACK_ICE, Label.UNKNOWN):
            label = Label.FREEZING
    return replace(score, label=label, confidence=conf, reason=f"{score.reason}; {note}")
