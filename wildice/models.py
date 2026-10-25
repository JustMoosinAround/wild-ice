"""Shared data models."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Label(StrEnum):
    OPEN_WATER = "open_water"
    FREEZING = "freezing"
    LIKELY_BLACK_ICE = "likely_black_ice"
    SNOW_COVERED = "snow_covered"
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SurfaceClass(StrEnum):
    WHITE = "white"
    DARK = "dark"
    GREY = "grey"


class ResetKind(StrEnum):
    FREEZE_UP = "freeze_up"
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    POSSIBLE = "possible"


@dataclass(frozen=True)
class Lake:
    id: str
    name: str | None
    area_acres: float
    road_mi: float | None
    trail_mi: float | None
    lat: float
    lon: float
    interior: dict | None  # GeoJSON geometry, EPSG:4326
    warning: str | None


@dataclass(frozen=True)
class DayWeather:
    day: date
    t_min: float
    t_max: float
    t_mean: float
    snowfall_cm: float
    rain_mm: float
    gust_kmh: float


@dataclass(frozen=True)
class ResetEvent:
    day: date
    kind: ResetKind


@dataclass(frozen=True)
class IceState:
    cum_fdd: float
    thickness_cm: float
    freeze_up: date | None
    last_reset: ResetEvent | None
    snow_since_reset_cm: float
    last_snow_day: date | None
    possible_resets: tuple[ResetEvent, ...]


@dataclass(frozen=True)
class S2Obs:
    day: date
    valid_fraction: float
    b03: float
    b04: float
    b11: float


@dataclass(frozen=True)
class S1Obs:
    day: date
    vv_db: float


@dataclass(frozen=True)
class ImageryStats:
    s2: tuple[S2Obs, ...]
    s1: tuple[S1Obs, ...]
    s1_baseline_db: float | None


@dataclass(frozen=True)
class Score:
    lake_id: str
    label: Label
    confidence: Confidence
    reason: str
    thickness_cm: float
    last_clear_day: date | None
