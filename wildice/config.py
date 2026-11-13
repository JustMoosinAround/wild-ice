"""Load and validate config.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class RegionCfg:
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class FiltersCfg:
    min_area_acres: float
    max_road_miles: float
    max_trail_miles: float
    min_area_acres_at_road: float


@dataclass(frozen=True)
class IceCfg:
    ashton_h: float
    skate_cm: float
    open_cm: float
    water_start_c: float


@dataclass(frozen=True)
class SnowCfg:
    cover_cm: float


@dataclass(frozen=True)
class ResetCfg:
    rain_mm: float
    thaw_days: int
    wind_gust_kmh: float
    light_snow_cm: float


@dataclass(frozen=True)
class ImageryCfg:
    min_valid_fraction: float
    fresh_days: int
    shore_buffer_m: float
    snow_ndsi: float
    snow_brightness: float
    dark_brightness: float
    s1_frozen_delta_db: float
    lookback_days: int
    monthly_request_budget: int
    max_lakes_per_day: int
    max_minutes_per_run: float
    patchy_texture: float  # S2Obs.texture at or above this: grey ice with black patches
    patch_days: int        # how long a patch seen on a clear image is remembered
    low_sun_start: str  # MM-DD
    low_sun_end: str  # MM-DD, may wrap the new year
    ls_snow_brightness: float  # Landsat's own thresholds (top-of-atmosphere reflectance)
    ls_dark_brightness: float
    ls_open_water_c: float  # a dark Landsat look at or above this is open water


@dataclass(frozen=True)
class RidgesCfg:
    min_span_mi: float      # lakes at least this long can grow pressure ridges
    warmup_c: float         # daily-mean rise after a cold spell that triggers a warning
    window_days: int        # how recent the warm-up or thaw must be
    thaw_gust_kmh: float    # a thaw day this windy may open old ridges
    points_index: float     # shoreline development index for "many points and bays"
    big_ice_mi: float       # lakes this long are "big ice": leads, open areas, moving sheets
    lead_min_span_mi: float  # wind can split sheets about this long into leads
    lead_gust_kmh: float    # gusts that open leads (~30 mph in the lakeice.org account)
    lead_max_cm: float      # ice at or under this is thin enough to split (unless thawed)


@dataclass(frozen=True)
class WeatherCfg:
    batch_pause_s: float


@dataclass(frozen=True)
class SiteCfg:
    base_url: str


@dataclass(frozen=True)
class Config:
    region: RegionCfg
    filters: FiltersCfg
    ice: IceCfg
    snow: SnowCfg
    reset: ResetCfg
    imagery: ImageryCfg
    ridges: RidgesCfg
    weather: WeatherCfg
    site: SiteCfg
    season_start: str
    pinned: tuple[str, ...]
    hidden: tuple[str, ...]


def _get(d: dict, key: str, path: str = ""):
    full = f"{path}.{key}" if path else key
    if not isinstance(d, dict) or key not in d:
        raise ConfigError(f"missing config key: {full}")
    return d[key]


def _mmdd(value) -> str:
    text = str(value)
    try:
        month, day = (int(x) for x in text.split("-"))
        date(2000, month, day)  # leap year: accepts 02-29
    except (TypeError, ValueError):
        raise ConfigError(f"expected MM-DD, got {text!r}") from None
    return text


def _section(raw: dict, name: str, cls, casts: dict):
    sec = _get(raw, name)
    if not isinstance(sec, dict):
        raise ConfigError(f"config key must be a mapping: {name}")
    return cls(**{k: cast(_get(sec, k, name)) for k, cast in casts.items()})


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("config is empty or not a mapping")

    missing = [k for k in ("region", "filters", "ice", "snow", "reset", "imagery", "ridges", "weather", "site",
                           "season_start", "pinned", "hidden") if k not in raw]
    if missing:
        raise ConfigError(f"missing config key(s): {', '.join(missing)}")

    region = _get(raw, "region")
    bbox = _get(region, "bbox", "region")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ConfigError("region.bbox must have 4 numbers")

    return Config(
        region=RegionCfg(bbox=tuple(float(x) for x in bbox)),
        filters=_section(raw, "filters", FiltersCfg,
                         dict(min_area_acres=float, max_road_miles=float, max_trail_miles=float,
                              min_area_acres_at_road=float)),
        ice=_section(raw, "ice", IceCfg, dict(ashton_h=float, skate_cm=float, open_cm=float,
                                                         water_start_c=float)),
        snow=_section(raw, "snow", SnowCfg, dict(cover_cm=float)),
        reset=_section(raw, "reset", ResetCfg,
                       dict(rain_mm=float, thaw_days=int, wind_gust_kmh=float, light_snow_cm=float)),
        imagery=_section(raw, "imagery", ImageryCfg, dict(
            min_valid_fraction=float, fresh_days=int, shore_buffer_m=float,
            snow_ndsi=float, snow_brightness=float, dark_brightness=float,
            s1_frozen_delta_db=float, lookback_days=int, monthly_request_budget=int,
            max_lakes_per_day=int, max_minutes_per_run=float, patchy_texture=float, patch_days=int,
            low_sun_start=_mmdd, low_sun_end=_mmdd,
            ls_snow_brightness=float, ls_dark_brightness=float, ls_open_water_c=float)),
        ridges=_section(raw, "ridges", RidgesCfg, dict(
            min_span_mi=float, warmup_c=float, window_days=int, thaw_gust_kmh=float,
            points_index=float, big_ice_mi=float, lead_min_span_mi=float,
            lead_gust_kmh=float, lead_max_cm=float)),
        weather=_section(raw, "weather", WeatherCfg, dict(batch_pause_s=float)),
        site=_section(raw, "site", SiteCfg, dict(base_url=str)),
        season_start=str(_get(raw, "season_start")),
        pinned=tuple(str(x) for x in (_get(raw, "pinned") or [])),
        hidden=tuple(str(x) for x in (_get(raw, "hidden") or [])),
    )
