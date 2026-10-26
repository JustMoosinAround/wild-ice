"""Scoring: turn ice-model state plus satellite stats into a user-facing label."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from wildice.config import Config
from wildice.icemodel import in_low_sun
from wildice.models import (
    Confidence, IceState, ImageryStats, Label, Lake, ResetKind, S1Obs, S2Obs, Score, SurfaceClass,
)

_RESET_PHRASE = {
    ResetKind.FREEZE_UP: "freeze-up",
    ResetKind.CONFIRMED: "clearing",
    ResetKind.LIKELY: "rain/thaw",
}


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"


def classify_s2(obs: S2Obs, cfg: Config) -> SurfaceClass | None:
    im = cfg.imagery
    if obs.valid_fraction < im.min_valid_fraction:
        return None
    brightness = (obs.b03 + obs.b04) / 2
    denom = obs.b03 + obs.b11
    ndsi = (obs.b03 - obs.b11) / denom if denom else 0.0
    if ndsi >= im.snow_ndsi and brightness >= im.snow_brightness:
        return SurfaceClass.WHITE
    if brightness <= im.dark_brightness:
        return SurfaceClass.DARK
    return SurfaceClass.GREY


def valid_s2_classes(imagery: ImageryStats | None, cfg: Config) -> dict[date, SurfaceClass]:
    out: dict[date, SurfaceClass] = {}
    if imagery is None:
        return out
    for obs in imagery.s2:
        cls = classify_s2(obs, cfg)
        if cls is not None:
            out[obs.day] = cls
    return out


def s1_frozen(obs: S1Obs, baseline_db: float | None, cfg: Config) -> bool | None:
    if baseline_db is None:
        return None
    return obs.vv_db - baseline_db >= cfg.imagery.s1_frozen_delta_db


def score_lake(lake: Lake, ice: IceState, imagery: ImageryStats | None,
               run_date: date, cfg: Config,
               s2_history: Mapping[date, SurfaceClass] | None = None) -> Score:
    """`s2_history` holds this season's earlier valid S2 classes; today's imagery wins."""
    h = ice.thickness_cm
    classes = {**(s2_history or {}), **valid_s2_classes(imagery, cfg)}
    last_clear_day = max(classes) if classes else None
    latest_cls = classes[last_clear_day] if last_clear_day else None
    latest_s1 = max(imagery.s1, key=lambda o: o.day) if imagery and imagery.s1 else None

    window_start = run_date - timedelta(days=cfg.imagery.lookback_days)
    s2_in_window = any(window_start <= d <= run_date for d in classes)
    radar_frozen = bool(latest_s1 and not s2_in_window
                        and s1_frozen(latest_s1, imagery.s1_baseline_db, cfg))

    snow = ice.snow_since_reset_cm
    cover = cfg.snow.cover_cm
    if ice.last_snow_day is None:
        s2_after_snow = last_clear_day is not None
    else:
        s2_after_snow = last_clear_day is not None and last_clear_day > ice.last_snow_day

    if h < cfg.ice.open_cm:
        label = Label.OPEN_WATER
    elif latest_cls is SurfaceClass.WHITE or (snow > cover and not s2_after_snow):
        label = Label.SNOW_COVERED
    elif h < cfg.ice.skate_cm:
        label = Label.FREEZING
    elif snow <= cover and (latest_cls is SurfaceClass.DARK or radar_frozen):
        label = Label.LIKELY_BLACK_ICE
    else:
        label = Label.UNKNOWN

    fresh_cut = run_date - timedelta(days=cfg.imagery.fresh_days)
    if last_clear_day is not None and last_clear_day >= fresh_cut:
        conf = Confidence.HIGH
    elif last_clear_day is not None or latest_s1 is not None:
        conf = Confidence.MEDIUM
    else:
        conf = Confidence.LOW
    if (label is Label.LIKELY_BLACK_ICE and conf is Confidence.HIGH
            and ice.last_reset is not None and ice.last_reset.kind is ResetKind.LIKELY):
        conf = Confidence.MEDIUM

    # A dark S2 alone can be open water (radar disagrees) or low-sun shading.
    caveats: list[str] = []
    if label is Label.LIKELY_BLACK_ICE:
        if latest_s1 is not None and s1_frozen(latest_s1, imagery.s1_baseline_db, cfg) is False:
            caveats.append("radar does not confirm ice")
        if latest_cls is SurfaceClass.DARK and in_low_sun(last_clear_day, cfg):
            caveats.append("low sun")
    if caveats and conf is Confidence.HIGH:
        conf = Confidence.MEDIUM

    parts = [f"~{h:.0f} cm est."]
    if snow > 0:
        if ice.last_reset:
            parts.append(f"{snow:.0f} cm snow since {_fmt(ice.last_reset.day)}")
        elif ice.last_snow_day:
            parts.append(f"{snow:.0f} cm snow, last on {_fmt(ice.last_snow_day)}")
        else:
            parts.append(f"{snow:.0f} cm snow")
    elif ice.last_reset is not None:
        phrase = _RESET_PHRASE.get(ice.last_reset.kind, "reset")
        parts.append(f"no snow since {phrase} on {_fmt(ice.last_reset.day)}")
    else:
        parts.append("no snow recorded")
    if latest_cls is SurfaceClass.DARK:
        parts.append(f"dark on {_fmt(last_clear_day)} image")
    elif latest_cls is SurfaceClass.WHITE:
        parts.append(f"white on {_fmt(last_clear_day)} image")
    elif radar_frozen and label is Label.LIKELY_BLACK_ICE:
        parts.append("radar suggests ice")
    elif last_clear_day is not None:
        parts.append(f"no clear image since {_fmt(last_clear_day)}")
    else:
        parts.append("no clear image")
    if ice.possible_resets:
        latest_pr = max(ice.possible_resets, key=lambda e: e.day)
        parts.append(f"possible wind clearing {_fmt(latest_pr.day)}")
    parts.extend(caveats)

    return Score(lake.id, label, conf, "; ".join(parts), h, last_clear_day)
