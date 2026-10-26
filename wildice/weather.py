"""Daily weather from Open-Meteo, cached per 0.1 degree grid cell."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from wildice.config import Config
from wildice.models import DayWeather, SourceUnavailable

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SOURCE = "open-meteo"
BATCH = 50
TIMEOUT_S = 60
TIMEZONE = "America/Anchorage"
DAILY_VARS = ("temperature_2m_min,temperature_2m_max,temperature_2m_mean,"
              "snowfall_sum,rain_sum,wind_gusts_10m_max")

Cell = tuple[float, float]


def make_session() -> requests.Session:
    """Session that retries transient failures with backoff."""
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=frozenset({"GET", "POST"}))
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def season_start(run_date: date, cfg: Config) -> date:
    month, day = (int(x) for x in cfg.season_start.split("-"))
    start = date(run_date.year, month, day)
    return start if start <= run_date else date(run_date.year - 1, month, day)


def cell_of(lat: float, lon: float) -> Cell:
    return (round(lat, 1), round(lon, 1))


def parse_location(daily: dict) -> list[DayWeather]:
    """Parse one Open-Meteo daily block; days lacking temperatures are dropped."""
    out: list[DayWeather] = []
    for i, day in enumerate(daily["time"]):
        t_min = daily["temperature_2m_min"][i]
        t_max = daily["temperature_2m_max"][i]
        t_mean = daily["temperature_2m_mean"][i]
        if t_min is None or t_max is None or t_mean is None:
            continue
        snow = daily["snowfall_sum"][i]
        rain = daily["rain_sum"][i]
        gust = daily["wind_gusts_10m_max"][i]
        out.append(DayWeather(
            day=date.fromisoformat(day), t_min=t_min, t_max=t_max, t_mean=t_mean,
            snowfall_cm=0.0 if snow is None else snow,
            rain_mm=0.0 if rain is None else rain,
            gust_kmh=0.0 if gust is None else gust,
        ))
    return out


def _get(session: requests.Session, url: str, params: dict) -> list[dict]:
    try:
        resp = session.get(url, params=params, timeout=TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise SourceUnavailable(SOURCE, str(exc)) from exc
    return data if isinstance(data, list) else [data]


def fetch_daily(cells: list[Cell], start: date, end: date, session: requests.Session,
                archive: bool) -> dict[Cell, list[DayWeather]]:
    result: dict[Cell, list[DayWeather]] = {}
    for i in range(0, len(cells), BATCH):
        batch = cells[i:i + BATCH]
        params = {
            "latitude": ",".join(str(c[0]) for c in batch),
            "longitude": ",".join(str(c[1]) for c in batch),
            "daily": DAILY_VARS,
            "timezone": TIMEZONE,
        }
        if archive:
            url = ARCHIVE_URL
            params["start_date"] = start.isoformat()
            params["end_date"] = end.isoformat()
        else:
            url = FORECAST_URL
            params["past_days"] = 14
            params["forecast_days"] = 1
        locations = _get(session, url, params)
        if len(locations) != len(batch):
            raise SourceUnavailable(
                SOURCE, f"expected {len(batch)} locations, got {len(locations)}")
        for cell, loc in zip(batch, locations):
            days = parse_location(loc["daily"])
            if not archive:
                days = [d for d in days if d.day <= end]
            result[cell] = days
    return result


def _cache_path(cache_dir: Path, cell: Cell) -> Path:
    return Path(cache_dir) / f"{cell[0]}_{cell[1]}.json"


def _load(path: Path) -> list[DayWeather]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [DayWeather(day=date.fromisoformat(r["day"]), t_min=r["t_min"],
                       t_max=r["t_max"], t_mean=r["t_mean"],
                       snowfall_cm=r["snowfall_cm"], rain_mm=r["rain_mm"],
                       gust_kmh=r["gust_kmh"]) for r in rows]


def _save(path: Path, days: list[DayWeather]) -> None:
    rows = [{**d.__dict__, "day": d.day.isoformat()} for d in days]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8", newline="\n")


def _merge(*lists: list[DayWeather]) -> list[DayWeather]:
    by_day: dict[date, DayWeather] = {}
    for lst in lists:  # later lists overwrite earlier
        for d in lst:
            by_day[d.day] = d
    return [by_day[k] for k in sorted(by_day)]


def _is_complete(days: list[DayWeather], start: date, run_date: date) -> bool:
    """True if cached days start at season start, reach within the forecast
    window (past_days=14) of run_date, and have no gaps."""
    if not days or days[0].day != start:
        return False
    if days[-1].day < run_date - timedelta(days=13):
        return False
    return (days[-1].day - start).days + 1 == len(days)


def update_cache(cache_dir: Path, cells: list[Cell], run_date: date, cfg: Config,
                 session: requests.Session) -> dict[Cell, list[DayWeather]]:
    start = season_start(run_date, cfg)
    cached: dict[Cell, list[DayWeather]] = {}
    fresh: list[Cell] = []
    for cell in cells:
        path = _cache_path(cache_dir, cell)
        days = _load(path) if path.exists() else []
        days = [d for d in days if d.day >= start]
        if _is_complete(days, start, run_date):
            cached[cell] = days
        else:  # missing, stale, or gappy: backfill from season start
            cached[cell] = days
            fresh.append(cell)
    backfill = fetch_daily(fresh, start, run_date, session, archive=True) if fresh else {}
    recent = fetch_daily(cells, start, run_date, session, archive=False) if cells else {}
    out: dict[Cell, list[DayWeather]] = {}
    for cell in cells:
        days = _merge(cached.get(cell, []), backfill.get(cell, []), recent[cell])
        days = [d for d in days if d.day >= start]
        _save(_cache_path(cache_dir, cell), days)
        out[cell] = days
    return out
