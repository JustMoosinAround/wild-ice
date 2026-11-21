"""Measured new snow from free, same-day stations: NRCS SNOTEL and CoCoRaHS volunteers.

The weather model's snowfall is unreliable near freezing (Nov 18-19 2026 it called 4-8 in
of wet snow "27 mm of rain"). Where a lake has a station close enough, the station's
measured new snow replaces the model's for the days it reported.
See docs/superpowers/specs/2026-11-21-snow-stations-design.md.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

import requests

from wildice.config import Config
from wildice.models import DayWeather, Lake

log = logging.getLogger(__name__)

CM_PER_IN = 2.54
M_PER_FT = 0.3048
TIMEOUT_S = 90
SNOTEL_URL = ("https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customMultipleStationReport/"
              "daily/state=%22AK%22%20AND%20network=%22SNTL%22%20AND%20element=%22SNWD%22"
              "%20AND%20outServiceDate=%222100-01-01%22%7Cname/{start},{end}/"
              "name,stationId,latitude,longitude,elevation,SNWD::value,WTEQ::value")
SNOTEL_URL_RE = re.compile(r"https://wcc\.sc\.egov\.usda\.gov/reportGenerator/view_csv/.*")
COCORAHS_URL = re.compile(r"https://data\.cocorahs\.org/export/exportreports\.aspx.*")
_COCORAHS_BASE = "https://data.cocorahs.org/export/exportreports.aspx"

Obs = dict[str, dict[date, float]]  # station id -> day -> new snow (cm) that fell that day


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    lat: float
    lon: float
    elev_m: float | None
    source: str  # "SNOTEL" or "CoCoRaHS"


def _num(text: str) -> float | None:
    t = (text or "").strip()
    if t.upper() == "T":
        return 0.0  # trace
    try:
        return float(t)
    except ValueError:
        return None


def parse_snotel(text: str) -> tuple[list[Station], Obs]:
    """Start-of-day depth/SWE rows -> new snow on day D = rise from D to D+1, counted
    only when the water content rose too (a depth rise alone is drifting)."""
    rows = csv.DictReader(l for l in io.StringIO(text) if not l.startswith("#"))
    stations: dict[str, Station] = {}
    series: dict[str, dict[date, tuple[float | None, float | None]]] = {}
    for r in rows:
        try:
            sid = "snotel:" + r["Station Id"].strip()
            day = date.fromisoformat(r["Date"].strip())
            if sid not in stations:
                elev = _num(r.get("Elevation (ft)", ""))
                stations[sid] = Station(sid, r["Station Name"].strip(), float(r["Latitude"]),
                                        float(r["Longitude"]),
                                        elev * M_PER_FT if elev is not None else None, "SNOTEL")
        except (KeyError, ValueError, AttributeError):
            continue
        depth = _num(r.get("Snow Depth (in) Start of Day Values", ""))
        swe = _num(r.get("Snow Water Equivalent (in) Start of Day Values", ""))
        series.setdefault(sid, {})[day] = (depth, swe)
    obs: Obs = {}
    for sid, days in series.items():
        for d, (depth, swe) in days.items():
            nxt = days.get(d + timedelta(days=1))
            if nxt is None or depth is None or nxt[0] is None:
                continue
            rise = nxt[0] - depth
            wetter = swe is None or nxt[1] is None or nxt[1] > swe
            obs.setdefault(sid, {})[d] = round(rise * CM_PER_IN, 2) if rise > 0 and wetter else 0.0
    return list(stations.values()), obs


def parse_cocorahs(text: str, bbox: Sequence[float]) -> tuple[list[Station], Obs]:
    """Daily reports -> new snow on the day before the (morning) report; 'NA' says nothing."""
    south, west, north, east = bbox
    stations: dict[str, Station] = {}
    obs: Obs = {}
    for r in csv.DictReader(io.StringIO(text), skipinitialspace=True):
        try:
            lat, lon = float(r["Latitude"]), float(r["Longitude"])
            day = date.fromisoformat(r["ObservationDate"].strip()) - timedelta(days=1)
            sid = "cocorahs:" + r["StationNumber"].strip()
        except (KeyError, ValueError, AttributeError):
            continue
        if not (south <= lat <= north and west <= lon <= east):
            continue
        stations.setdefault(sid, Station(sid, r["StationName"].strip(), lat, lon, None, "CoCoRaHS"))
        new = _num(r.get("NewSnowDepth", ""))
        if new is not None:
            obs.setdefault(sid, {})[day] = round(new * CM_PER_IN, 2)
    return list(stations.values()), obs


def _km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dlat, dlon = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def match_station(lake: Lake, stations: Sequence[Station], cfg: Config) -> Station | None:
    """Nearest station within max_km at a similar height. Without both heights, only
    lowland pairs match (volunteer stations have no height and sit in towns)."""
    s_cfg = cfg.snowobs
    best = None
    for s in stations:
        if s.elev_m is not None and lake.elev_m is not None:
            ok = abs(s.elev_m - lake.elev_m) <= s_cfg.max_dz_m
        elif s.elev_m is None and lake.elev_m is None:
            ok = True
        else:
            known = s.elev_m if s.elev_m is not None else lake.elev_m
            ok = known <= s_cfg.lowland_m
        if not ok:
            continue
        km = _km(lake.lat, lake.lon, s.lat, s.lon)
        if km <= s_cfg.max_km and (best is None or km < best[0]):
            best = (km, s)
    return best[1] if best else None


def apply_measured(days: Sequence[DayWeather], measured: Mapping[date, float]) -> list[DayWeather]:
    """The station's new snow replaces the weather model's on days it reported; measured
    snow also means the day's precipitation fell as snow, not rain."""
    out = []
    for d in days:
        cm = measured.get(d.day)
        if cm is not None:
            d = replace(d, snowfall_cm=cm, rain_mm=0.0 if cm > 0 else d.rain_mm)
        out.append(d)
    return out


def latest_measured(measured: Mapping[date, float], run_date: date, days: int
                    ) -> tuple[date, float] | None:
    since = run_date - timedelta(days=days)
    hits = [(d, cm) for d, cm in measured.items() if since <= d <= run_date and cm > 0]
    return max(hits) if hits else None


def fetch_observations(session: requests.Session, start: date, end: date, cfg: Config
                       ) -> tuple[list[Station], Obs]:
    """Both sources for start..end; a source that fails is logged and skipped."""
    stations: list[Station] = []
    obs: Obs = {}
    try:
        r = session.get(SNOTEL_URL.format(start=start.isoformat(), end=end.isoformat()),
                        timeout=TIMEOUT_S)
        r.raise_for_status()
        s, o = parse_snotel(r.text)
        stations += s
        obs.update(o)
    except requests.RequestException as exc:
        log.error("SNOTEL unavailable: %s", type(exc).__name__)
    try:
        # CoCoRaHS reports the morning after: ask one day past the end for the last day's snow
        r = session.get(_COCORAHS_BASE, timeout=TIMEOUT_S, params={
            "ReportType": "Daily", "dtf": "1", "Format": "CSV", "State": "AK",
            "ReportDateType": "reportdate", "TimesInGMT": "False",
            "StartDate": (start + timedelta(days=1)).strftime("%m/%d/%Y"),
            "EndDate": (end + timedelta(days=1)).strftime("%m/%d/%Y")})
        r.raise_for_status()
        if not r.text.lstrip().startswith("ObservationDate"):
            raise ValueError("not a CoCoRaHS CSV")
        s, o = parse_cocorahs(r.text, cfg.region.bbox)
        stations += s
        obs.update(o)
    except (requests.RequestException, ValueError) as exc:
        log.error("CoCoRaHS unavailable: %s", type(exc).__name__)
    return stations, obs
