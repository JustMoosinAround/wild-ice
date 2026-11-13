"""Scoring: turn ice-model state plus satellite stats into a user-facing label."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from wildice.config import Config
from wildice.icemodel import in_low_sun
from wildice.models import (
    Confidence, IceState, ImageryStats, Label, Lake, LSObs, ResetKind, S1Obs, S2Obs, Score,
    SurfaceClass,
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


def classify_ls(obs: LSObs, cfg: Config) -> SurfaceClass | None:
    """Landsat 8-9 look: Sentinel-2's rules on Landsat's own brightness scale, plus its
    thermal band: a dark surface above freezing is open water, not ice."""
    im = cfg.imagery
    if obs.valid_fraction < im.min_valid_fraction:
        return None
    brightness = (obs.b03 + obs.b04) / 2
    denom = obs.b03 + obs.b06
    ndsi = (obs.b03 - obs.b06) / denom if denom else 0.0
    if ndsi >= im.snow_ndsi and brightness >= im.ls_snow_brightness:
        return SurfaceClass.WHITE
    if brightness <= im.ls_dark_brightness:
        return SurfaceClass.WATER if obs.temp_c >= im.ls_open_water_c else SurfaceClass.DARK
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


def valid_ls_classes(imagery: ImageryStats | None, cfg: Config) -> dict[date, SurfaceClass]:
    out: dict[date, SurfaceClass] = {}
    if imagery is None:
        return out
    for obs in imagery.ls:
        cls = classify_ls(obs, cfg)
        if cls is not None:
            out[obs.day] = cls
    return out


def optical_classes(s2: Mapping[date, SurfaceClass] | None,
                    ls: Mapping[date, SurfaceClass] | None) -> dict[date, SurfaceClass]:
    """Both cameras' clear looks by day; Sentinel-2 wins a day both saw."""
    return {**(ls or {}), **(s2 or {})}


def s1_frozen(obs: S1Obs, baseline_db: float | None, cfg: Config) -> bool | None:
    if baseline_db is None:
        return None
    return obs.vv_db - baseline_db >= cfg.imagery.s1_frozen_delta_db


def score_lake(lake: Lake, ice: IceState, imagery: ImageryStats | None,
               run_date: date, cfg: Config,
               s2_history: Mapping[date, SurfaceClass] | None = None,
               ls_history: Mapping[date, SurfaceClass] | None = None) -> Score:
    """`s2_history` / `ls_history` hold this season's earlier valid Sentinel-2 / Landsat
    classes; today's imagery wins."""
    h = ice.thickness_cm
    s2_classes = {**(s2_history or {}), **valid_s2_classes(imagery, cfg)}
    classes = optical_classes(s2_classes,
                              {**(ls_history or {}), **valid_ls_classes(imagery, cfg)})
    last_clear_day = max(classes) if classes else None
    latest_cls = classes[last_clear_day] if last_clear_day else None
    sensor = "ls" if last_clear_day is not None and last_clear_day not in s2_classes else "s2"
    latest_s1 = max(imagery.s1, key=lambda o: o.day) if imagery and imagery.s1 else None

    window_start = run_date - timedelta(days=cfg.imagery.lookback_days)
    s2_in_window = any(window_start <= d <= run_date for d in classes)
    # open water seen on Landsat's thermal band; older looks may have frozen over since
    seen_water = (latest_cls is SurfaceClass.WATER and last_clear_day is not None
                  and last_clear_day >= window_start)
    radar_frozen = bool(latest_s1 and not s2_in_window
                        and s1_frozen(latest_s1, imagery.s1_baseline_db, cfg))
    # Crack lines on a dark lake: today's imagery only (history keeps classes, not texture).
    cracked_day = None
    for obs in (imagery.s2 if imagery else ()):
        if (obs.texture is not None and obs.texture >= cfg.imagery.crack_texture
                and classify_s2(obs, cfg) is SurfaceClass.DARK
                and (cracked_day is None or obs.day > cracked_day)):
            cracked_day = obs.day
    if cracked_day != last_clear_day:  # a later clear look (e.g. white) wins
        cracked_day = None

    snow = ice.snow_since_reset_cm
    cover = cfg.snow.cover_cm
    if ice.last_snow_day is None:
        s2_after_snow = last_clear_day is not None
    else:
        s2_after_snow = last_clear_day is not None and last_clear_day > ice.last_snow_day

    if h < cfg.ice.open_cm or seen_water:
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
        if (latest_s1 is not None and cracked_day is None
                and s1_frozen(latest_s1, imagery.s1_baseline_db, cfg) is False):
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
    image = "Landsat image" if sensor == "ls" else "image"
    if cracked_day is not None:
        parts.append(f"crack lines on {_fmt(cracked_day)} image")
    elif latest_cls is SurfaceClass.WATER:
        parts.append(f"open water (above freezing) on {_fmt(last_clear_day)} {image}")
    elif latest_cls is SurfaceClass.DARK:
        parts.append(f"dark on {_fmt(last_clear_day)} {image}")
    elif latest_cls is SurfaceClass.WHITE:
        parts.append(f"white on {_fmt(last_clear_day)} {image}")
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

    return Score(lake.id, label, conf, "; ".join(parts), h, last_clear_day, sensor)
