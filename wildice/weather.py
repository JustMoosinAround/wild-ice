"""Daily weather from Open-Meteo, cached per 0.1 degree grid cell.

Each cell is requested at one real point (the largest lake in it) rather than at the
rounded cell centre, which can sit on a ridge or in the sea.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
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
RATE_LIMIT_WAIT_S = 60  # after a 429, wait this long and retry once
DAILY_VARS = ("temperature_2m_min,temperature_2m_max,temperature_2m_mean,"
              "snowfall_sum,rain_sum,wind_gusts_10m_max")

Cell = tuple[float, float]
Point = tuple[float, float]  # (lat, lon) actually sent to Open-Meteo
Sleep = Callable[[float], None]


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


def cell_points(lakes: Iterable) -> dict[Cell, Point]:
    """Request point per cell: the coordinates of the largest lake (by area) in it."""
    best: dict[Cell, object] = {}
    for lake in lakes:
        cell = cell_of(lake.lat, lake.lon)
        if cell not in best or lake.area_acres > best[cell].area_acres:
            best[cell] = lake
    return {cell: (best[cell].lat, best[cell].lon) for cell in sorted(best)}


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


def _rate_limited(exc: Exception) -> bool:
    """A 429 response, or urllib3 giving up after repeated 429s (make_session)."""
    if isinstance(exc, requests.HTTPError):
        return exc.response is not None and exc.response.status_code == 429
    return isinstance(exc, requests.exceptions.RetryError) and "429" in str(exc)


def _get(session: requests.Session, url: str, params: dict, sleep: Sleep) -> list[dict]:
    for attempt in range(2):
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT_S)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == 0 and _rate_limited(exc):
                sleep(RATE_LIMIT_WAIT_S)
                continue
            raise SourceUnavailable(SOURCE, str(exc)) from exc
        return data if isinstance(data, list) else [data]
    raise AssertionError("unreachable")


def fetch_daily(cells: Sequence[Cell], start: date, end: date, session: requests.Session,
                archive: bool, points: Mapping[Cell, Point] | None = None,
                pause_s: float = 0.0, sleep: Sleep | None = None,
                on_batch: Callable[[dict[Cell, list[DayWeather]]], None] | None = None,
                ) -> dict[Cell, list[DayWeather]]:
    """Fetch cells in batches, each at `points[cell]` (default: the cell itself).

    Sleeps `pause_s` between batches; `on_batch` sees each batch as soon as it lands.
    """
    sleep = sleep or time.sleep
    cells = list(cells)
    result: dict[Cell, list[DayWeather]] = {}
    for i in range(0, len(cells), BATCH):
        if i and pause_s > 0:
            sleep(pause_s)
        batch = cells[i:i + BATCH]
        pts = [points.get(c, c) if points else c for c in batch]
        params = {
            "latitude": ",".join(str(p[0]) for p in pts),
            "longitude": ",".join(str(p[1]) for p in pts),
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
        locations = _get(session, url, params, sleep)
        if len(locations) != len(batch):
            raise SourceUnavailable(
                SOURCE, f"expected {len(batch)} locations, got {len(locations)}")
        got: dict[Cell, list[DayWeather]] = {}
        for cell, loc in zip(batch, locations):
            days = parse_location(loc["daily"])
            if not archive:
                days = [d for d in days if d.day <= end]
            got[cell] = days
        result.update(got)
        if on_batch is not None:
            on_batch(got)
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


def update_cache(cache_dir: Path, cells: Mapping[Cell, Point] | Sequence[Cell],
                 run_date: date, cfg: Config, session: requests.Session,
                 sleep: Sleep | None = None) -> dict[Cell, list[DayWeather]]:
    """Bring every cell's cache up to run_date; `cells` maps cell -> request point
    (a plain list of cells requests each at its own rounded coordinates).

    Each batch is written to the cache as soon as it arrives, so a failure part-way
    keeps earlier progress for the next run.
    """
    sleep = sleep or time.sleep
    points = dict(cells) if isinstance(cells, Mapping) else {c: c for c in cells}
    order = list(points)
    start = season_start(run_date, cfg)
    pause = cfg.weather.batch_pause_s
    current: dict[Cell, list[DayWeather]] = {}
    fresh: list[Cell] = []
    for cell in order:
        path = _cache_path(cache_dir, cell)
        days = _load(path) if path.exists() else []
        current[cell] = [d for d in days if d.day >= start]
        if not _is_complete(current[cell], start, run_date):
            fresh.append(cell)  # missing, stale, or gappy: backfill from season start

    def keep(batch: dict[Cell, list[DayWeather]]) -> None:
        for cell, days in batch.items():  # later data overwrites earlier
            current[cell] = [d for d in _merge(current[cell], days) if d.day >= start]
            _save(_cache_path(cache_dir, cell), current[cell])

    if fresh:
        fetch_daily(fresh, start, run_date, session, archive=True, points=points,
                    pause_s=pause, sleep=sleep, on_batch=keep)
    if order:
        if fresh and pause > 0:
            sleep(pause)
        fetch_daily(order, start, run_date, session, archive=False, points=points,
                    pause_s=pause, sleep=sleep, on_batch=keep)
    return {cell: current[cell] for cell in order}
