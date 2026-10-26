import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from wildice.config import load_config
from wildice.models import SourceUnavailable
from wildice.weather import (
    ARCHIVE_URL, FORECAST_URL, cell_of, fetch_daily, parse_location, season_start,
    update_cache,
)

FIX = Path(__file__).parent / "fixtures"
cfg = load_config(Path("config.yaml"))


def block(days, mean=None, snow=None):
    n = len(days)
    return {"time": days,
            "temperature_2m_min": [-5.0] * n, "temperature_2m_max": [-1.0] * n,
            "temperature_2m_mean": mean if mean is not None else [-3.0] * n,
            "snowfall_sum": snow if snow is not None else [0.0] * n,
            "rain_sum": [0.0] * n, "wind_gusts_10m_max": [10.0] * n}


def test_season_start_before_oct():
    assert season_start(date(2026, 2, 1), cfg) == date(2025, 10, 1)


def test_season_start_after_oct():
    assert season_start(date(2026, 11, 5), cfg) == date(2026, 10, 1)


def test_season_start_on_day():
    assert season_start(date(2026, 10, 1), cfg) == date(2026, 10, 1)


def test_cell_rounding():
    assert cell_of(60.7725, -148.7965) == (60.8, -148.8)


def test_parse_drops_null_mean():
    b = block(["2025-11-01", "2025-11-02", "2025-11-03"], mean=[-3.0, -4.0, None])
    assert [d.day for d in parse_location(b)] == [date(2025, 11, 1), date(2025, 11, 2)]


def test_parse_null_snow_is_zero():
    b = block(["2025-11-01"], snow=[None])
    days = parse_location(b)
    assert days[0].snowfall_cm == 0.0


@responses.activate
def test_fetch_two_cells_fixture():
    data = json.loads((FIX / "openmeteo_two_cells.json").read_text())
    responses.add(responses.GET, ARCHIVE_URL, json=data)
    out = fetch_daily([(60.8, -148.8), (61.0, -149.5)], date(2025, 11, 1),
                      date(2025, 11, 2), requests.Session(), archive=True)
    assert out[(61.0, -149.5)][0].snowfall_cm == 0.0
    assert out[(60.8, -148.8)][1].snowfall_cm == 1.5
    q = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert q["start_date"] == ["2025-11-01"] and q["timezone"] == ["America/Anchorage"]


@responses.activate
def test_fetch_single_location_object():
    responses.add(responses.GET, FORECAST_URL, json={"daily": block(["2025-11-01"])})
    out = fetch_daily([(60.8, -148.8)], date(2025, 11, 1), date(2025, 11, 1),
                      requests.Session(), archive=False)
    assert len(out[(60.8, -148.8)]) == 1


@responses.activate
def test_fetch_forecast_trims_to_end():
    responses.add(responses.GET, FORECAST_URL,
                  json={"daily": block(["2025-11-01", "2025-11-02", "2025-11-03"])})
    out = fetch_daily([(60.8, -148.8)], date(2025, 11, 1), date(2025, 11, 2),
                      requests.Session(), archive=False)
    assert [d.day for d in out[(60.8, -148.8)]] == [date(2025, 11, 1), date(2025, 11, 2)]
    q = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert q["past_days"] == ["14"] and q["forecast_days"] == ["1"]


@responses.activate
def test_fetch_batches():
    def cb(request):
        q = parse_qs(urlparse(request.url).query)
        n = len(q["latitude"][0].split(","))
        assert n <= 50
        body = [{"daily": block(["2025-11-01"])} for _ in range(n)]
        return 200, {}, json.dumps(body)
    responses.add_callback(responses.GET, FORECAST_URL, callback=cb,
                           content_type="application/json")
    cells = [(60.0 + i * 0.1, -148.0) for i in range(120)]
    out = fetch_daily(cells, date(2025, 11, 1), date(2025, 11, 1),
                      requests.Session(), archive=False)
    assert len(responses.calls) == 3
    assert len(out) == 120


@responses.activate
def test_fetch_failure_raises_source_unavailable():
    responses.add(responses.GET, FORECAST_URL, status=503)
    with pytest.raises(SourceUnavailable) as ei:
        fetch_daily([(60.8, -148.8)], date(2025, 11, 1), date(2025, 11, 1),
                    requests.Session(), archive=False)
    assert ei.value.source == "open-meteo"


@responses.activate
def test_cache_backfills_then_merges(tmp_path):
    cell = (60.8, -148.8)
    arch = {"daily": block(["2025-10-01", "2025-10-02"], snow=[1.0, 2.0])}
    fc1 = {"daily": block(["2025-10-02", "2025-10-03"], snow=[9.0, 3.0])}
    responses.add(responses.GET, ARCHIVE_URL, json=arch)
    responses.add(responses.GET, FORECAST_URL, json=fc1)
    out = update_cache(tmp_path, [cell], date(2025, 10, 3), cfg, requests.Session())
    assert [d.day for d in out[cell]] == [date(2025, 10, d) for d in (1, 2, 3)]
    assert out[cell][1].snowfall_cm == 9.0  # forecast overwrites archive
    assert (tmp_path / "60.8_-148.8.json").exists()
    q = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert q["start_date"] == ["2025-10-01"] and q["end_date"] == ["2025-10-03"]
    assert len(responses.calls) == 2

    responses.calls.reset()
    responses.replace(responses.GET, FORECAST_URL,
                      json={"daily": block(["2025-10-03", "2025-10-04"], snow=[7.0, 4.0])})
    out = update_cache(tmp_path, [cell], date(2025, 10, 4), cfg, requests.Session())
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url.startswith(FORECAST_URL)
    assert [d.day for d in out[cell]] == [date(2025, 10, d) for d in (1, 2, 3, 4)]
    assert out[cell][2].snowfall_cm == 7.0
    assert out[cell][1].snowfall_cm == 9.0


def _seed(tmp_path, cell, days):
    from datetime import timedelta
    from wildice.weather import _save
    from wildice.models import DayWeather
    _save(tmp_path / f"{cell[0]}_{cell[1]}.json",
          [DayWeather(d, -5.0, -1.0, -3.0, 0.0, 0.0, 10.0) for d in days])


def _iso(d):
    return d.isoformat()


@responses.activate
def test_cache_stale_tail_triggers_archive(tmp_path):
    from datetime import timedelta
    cell = (60.8, -148.8)
    start, run = date(2025, 10, 1), date(2025, 10, 31)
    _seed(tmp_path, cell, [start + timedelta(days=i) for i in range(10)])  # last Oct 10
    all_days = [_iso(start + timedelta(days=i)) for i in range(31)]
    responses.add(responses.GET, ARCHIVE_URL, json={"daily": block(all_days[:29])})
    responses.add(responses.GET, FORECAST_URL, json={"daily": block(all_days[17:])})
    out = update_cache(tmp_path, [cell], run, cfg, requests.Session())
    assert any(c.request.url.startswith(ARCHIVE_URL) for c in responses.calls)
    assert [d.day for d in out[cell]] == [start + timedelta(days=i) for i in range(31)]


@responses.activate
def test_cache_middle_gap_triggers_archive(tmp_path):
    from datetime import timedelta
    cell = (60.8, -148.8)
    start, run = date(2025, 10, 1), date(2025, 10, 10)
    have = [start + timedelta(days=i) for i in range(10) if i != 4]
    _seed(tmp_path, cell, have)
    all_days = [_iso(start + timedelta(days=i)) for i in range(10)]
    responses.add(responses.GET, ARCHIVE_URL, json={"daily": block(all_days)})
    responses.add(responses.GET, FORECAST_URL, json={"daily": block(all_days[-5:])})
    out = update_cache(tmp_path, [cell], run, cfg, requests.Session())
    assert any(c.request.url.startswith(ARCHIVE_URL) for c in responses.calls)
    assert len(out[cell]) == 10


def test_make_session_retries_post_and_get():
    from wildice.weather import make_session
    retry = make_session().get_adapter("https://").max_retries
    assert retry.total == 3 and retry.backoff_factor == 2
    assert 503 in retry.status_forcelist and 429 in retry.status_forcelist
    assert retry.allowed_methods >= {"GET", "POST"}
