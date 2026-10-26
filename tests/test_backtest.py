from datetime import date, timedelta
from pathlib import Path

import pytest
import requests

from wildice import backtest
from wildice.backtest import Row, run_backtest, summarize
from wildice.models import Confidence, DayWeather, Label, S2Obs, SourceUnavailable

REPO = Path(__file__).resolve().parent.parent
DAY = date(2025, 12, 3)
START = date(2025, 10, 1)
POLY = {"type": "Polygon", "coordinates": [[[-149.51, 60.99], [-149.49, 60.99],
                                             [-149.49, 61.01], [-149.51, 61.01],
                                             [-149.51, 60.99]]]}


class FakeClient:
    def __init__(self, s2=None, fail=None):
        self.s2 = s2 or []
        self.fail = fail
        self.calls = []

    def s2_stats(self, geometry, start, end):
        self.calls.append(("s2", start, end))
        if self.fail:
            raise self.fail
        return list(self.s2)

    def s1_stats(self, geometry, start, end):
        self.calls.append(("s1", start, end))
        return []


def _days(end, t_mean=-8.0, snow_last=0.0):
    out = []
    d = START
    while d <= end:
        out.append(DayWeather(d, t_mean - 3, t_mean + 3, t_mean,
                              snow_last if d == end else 0.0, 0.0, 10.0))
        d += timedelta(days=1)
    return out


@pytest.fixture
def root(tmp_path):
    import json
    import shutil
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    data = tmp_path / "site" / "data"
    data.mkdir(parents=True)
    feat = {"type": "Feature", "geometry": POLY,
            "properties": {"id": "w1", "name": "Lake", "area_acres": 120.0, "road_mi": 0.5,
                           "trail_mi": None, "lat": 61.0, "lon": -149.5, "warning": None}}
    (data / "lakes.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": [feat]}), encoding="utf-8")
    return tmp_path


@pytest.fixture
def fake_weather(monkeypatch):
    state = {"snow": 0.0, "calls": []}

    def fetch(cells, start, end, session, archive, points=None, **kw):
        state["calls"].append((start, end, archive))
        state["points"] = points
        return {c: _days(end, snow_last=state["snow"]) for c in cells}

    monkeypatch.setattr(backtest, "fetch_daily", fetch)
    return state


def _obs(root, observed, day=DAY, lake="w1"):
    p = root / "backtest.yaml"
    p.write_text(f"observations:\n  - lake_id: {lake}\n    day: {day.isoformat()}\n"
                 f"    observed: {observed}\n", encoding="utf-8")
    return p


def _dark():
    return FakeClient(s2=[S2Obs(DAY - timedelta(days=1), 0.95, 0.05, 0.05, 0.02)])


def test_skated_day_matches(root, fake_weather):
    rows = run_backtest(_obs(root, "skated"), root, requests.Session(), _dark())
    assert rows[0].predicted is Label.LIKELY_BLACK_ICE
    assert rows[0].match is True
    assert fake_weather["calls"][0] == (START, DAY, True)


def test_snow_day_matches(root, fake_weather):
    fake_weather["snow"] = 5.0
    rows = run_backtest(_obs(root, "snow"), root, requests.Session(), None)
    assert rows[0].predicted is Label.SNOW_COVERED
    assert rows[0].match is True


def test_unknown_lake_is_error_line(root, fake_weather):
    rows = run_backtest(_obs(root, "skated", lake="w999"), root, requests.Session(), None)
    assert rows[0].match is False
    assert "w999" in summarize(rows)
    assert "error" in summarize(rows).lower()


def test_imagery_failure_is_error_line(root, fake_weather):
    client = FakeClient(fail=SourceUnavailable("copernicus"))
    rows = run_backtest(_obs(root, "skated"), root, requests.Session(), client)
    assert "error" in summarize(rows).lower()


def _row(observed, predicted):
    return Row("w1", DAY, observed, predicted, Confidence.HIGH, "r",
               predicted in backtest.EXPECTED[observed])


def test_false_alert_counted():
    rows = [_row("snow", Label.LIKELY_BLACK_ICE), _row("skated", Label.LIKELY_BLACK_ICE)]
    out = summarize(rows)
    assert "false alerts: 1" in out
    assert "matched 1/2" in out


def test_miss_counted():
    rows = [_row("skated", Label.UNKNOWN)]
    assert "misses: 1" in summarize(rows)


def test_weather_fetched_at_largest_lake_point(root, fake_weather):
    import json
    data = root / "site" / "data" / "lakes.geojson"
    fc = json.loads(data.read_text(encoding="utf-8"))
    big = json.loads(json.dumps(fc["features"][0]))
    big["properties"].update(id="w2", area_acres=500.0, lat=60.98, lon=-149.47)
    fc["features"].append(big)
    data.write_text(json.dumps(fc), encoding="utf-8")
    rows = run_backtest(_obs(root, "snow"), root, requests.Session(), None)
    assert rows[0].error is None
    assert fake_weather["points"][(61.0, -149.5)] == (60.98, -149.47)
