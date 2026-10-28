import json
import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
import responses as responses_lib

from wildice import run_daily
from wildice.models import S1Obs, S2Obs, SourceUnavailable
from wildice.run_daily import run
from wildice.weather import ARCHIVE_URL, FORECAST_URL

REPO = Path(__file__).resolve().parent.parent
RUN = date(2025, 11, 12)
SEASON_START = date(2025, 10, 1)
ENV = {"NTFY_TOPIC_ALERTS": "alerts-topic", "NTFY_TOPIC_OPS": "ops-topic"}
ALERTS_URL = "https://ntfy.sh/alerts-topic"
OPS_URL = "https://ntfy.sh/ops-topic"
POLY = {"type": "Polygon", "coordinates": [[[-149.51, 60.99], [-149.49, 60.99],
                                             [-149.49, 61.01], [-149.51, 61.01],
                                             [-149.51, 60.99]]]}


def _feature(lake_id, area, interior=POLY):
    return {"type": "Feature", "geometry": interior,
            "properties": {"id": lake_id, "name": f"Lake {lake_id}", "area_acres": area,
                           "road_mi": 0.5, "trail_mi": None, "lat": 61.0, "lon": -149.5,
                           "warning": None}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Weather pauses between batches; tests must not actually wait."""
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)


@pytest.fixture
def tmp_repo(tmp_path):
    shutil.copy(REPO / "config.yaml", tmp_path / "config.yaml")
    data = tmp_path / "site" / "data"
    data.mkdir(parents=True)
    (data / "lakes.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": [_feature("w1", 120.0)]}), encoding="utf-8")
    return tmp_path


def _daily(t_mean, end=RUN):
    days = [SEASON_START + timedelta(days=i) for i in range((end - SEASON_START).days + 1)]
    n = len(days)
    return {"latitude": 61.0, "longitude": -149.5, "daily": {
        "time": [d.isoformat() for d in days],
        "temperature_2m_min": [t_mean - 3] * n, "temperature_2m_max": [t_mean + 3] * n,
        "temperature_2m_mean": [t_mean] * n, "snowfall_sum": [0.0] * n,
        "rain_sum": [0.0] * n, "wind_gusts_10m_max": [10.0] * n}}


@pytest.fixture
def mocked():
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses_lib.POST, ALERTS_URL, status=200)
        rsps.add(responses_lib.POST, OPS_URL, status=200)
        yield rsps


def cold_weather(rsps, t_mean=-5.0):
    for url in (ARCHIVE_URL, FORECAST_URL):
        rsps.add(responses_lib.GET, url, json=[_daily(t_mean)], status=200)


def ntfy_calls(rsps, topic):
    return sum(1 for c in rsps.calls if c.request.url == f"https://ntfy.sh/{topic}")


def ntfy_bodies(rsps, topic):
    return [c.request.body.decode("utf-8") if isinstance(c.request.body, bytes)
            else c.request.body
            for c in rsps.calls if c.request.url == f"https://ntfy.sh/{topic}"]


class FakeClient:
    """Stands in for CopernicusClient (Task 7 methods)."""

    def __init__(self, s2=None, s1=None, fail=None):
        self.calls = []
        self.s2 = s2 if s2 is not None else [S2Obs(RUN - timedelta(days=1), 0.95, 0.05, 0.05, 0.02)]
        self.s1 = s1 if s1 is not None else []
        self.fail = fail

    def s2_stats(self, geometry, start, end):
        self.calls.append(("s2", start, end))
        if self.fail:
            raise self.fail
        return list(self.s2)

    def s1_stats(self, geometry, start, end):
        self.calls.append(("s1", start, end))
        if self.fail:
            raise self.fail
        return list(self.s1)

    def truecolor_png(self, geometry, day):
        self.calls.append(("png", day, day))
        return b"\x89PNG fake"

    def baseline_calls(self):
        return [c for c in self.calls if c[0] == "s1" and c[2] < RUN - timedelta(days=14)]


def status_of(root):
    return json.loads((root / "site/data/status.json").read_text(encoding="utf-8"))


def session():
    return requests.Session()


def test_happy_path_writes_status_and_alerts(tmp_repo, mocked):
    cold_weather(mocked)
    client = FakeClient()
    assert run(RUN, tmp_repo, ENV, session(), client) == 0
    status = status_of(tmp_repo)
    assert status["run_date"] == "2025-11-12"
    assert status["stale_since"] is None
    assert status["lakes"]["w1"]["label"] == "likely_black_ice"
    assert ntfy_calls(mocked, "alerts-topic") == 1
    assert ntfy_calls(mocked, "ops-topic") == 0
    assert (tmp_repo / "site/data/history/2025-11-12.json").exists()
    labels = json.loads((tmp_repo / "state/labels.json").read_text(encoding="utf-8"))
    assert labels == {"w1": "likely_black_ice"}
    usage = json.loads((tmp_repo / "state/usage.json").read_text(encoding="utf-8"))
    assert usage["month"] == "2025-11"


def test_second_run_same_result_no_alert(tmp_repo, mocked):
    cold_weather(mocked)
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
    assert ntfy_calls(mocked, "alerts-topic") == 1


def test_rerun_same_day_excludes_today_from_history(tmp_repo, mocked):
    cold_weather(mocked)
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
    days = [h["day"] for h in status_of(tmp_repo)["lakes"]["w1"]["history"]]
    assert "2025-11-12" not in days


def test_no_candidates_no_push(tmp_repo, mocked):
    cold_weather(mocked, t_mean=5.0)  # warm: open water everywhere
    client = FakeClient()
    assert run(RUN, tmp_repo, ENV, session(), client) == 0
    assert status_of(tmp_repo)["lakes"]["w1"]["label"] == "open_water"
    assert ntfy_calls(mocked, "alerts-topic") == 0
    assert client.calls == []  # not shortlisted


PREVIOUS = {"run_date": "2025-11-11", "stale_since": None, "disclaimer": "x",
            "lakes": {"w1": {"name": "Lake w1", "label": "freezing", "last_clear_day": None}}}


def _write_prev(root, prev):
    (root / "site/data/status.json").write_text(json.dumps(prev), encoding="utf-8")


def test_weather_down_marks_stale_and_pings_ops(tmp_repo, mocked, caplog):
    caplog.set_level(logging.DEBUG)
    _write_prev(tmp_repo, PREVIOUS)
    mocked.add(responses_lib.GET, ARCHIVE_URL, status=500)
    mocked.add(responses_lib.GET, FORECAST_URL, status=500)
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 1
    status = status_of(tmp_repo)
    assert status["stale_since"] == "2025-11-11"  # previous good run date
    assert status["lakes"] == PREVIOUS["lakes"]
    assert ntfy_calls(mocked, "ops-topic") == 1
    assert ntfy_bodies(mocked, "ops-topic") == ["open-meteo unavailable"]
    assert ntfy_calls(mocked, "alerts-topic") == 0
    assert not (tmp_repo / "site/data/history/2025-11-12.json").exists()
    assert "ops-topic" not in caplog.text and "alerts-topic" not in caplog.text


def test_already_stale_keeps_stale_since(tmp_repo, mocked):
    _write_prev(tmp_repo, {**PREVIOUS, "run_date": "2025-11-11", "stale_since": "2025-11-09"})
    mocked.add(responses_lib.GET, ARCHIVE_URL, status=500)
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 1
    assert status_of(tmp_repo)["stale_since"] == "2025-11-09"


def test_no_previous_status_writes_empty_stale(tmp_repo, mocked):
    mocked.add(responses_lib.GET, ARCHIVE_URL, status=500)
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 1
    status = status_of(tmp_repo)
    assert status["lakes"] == {}
    assert status["stale_since"] == "2025-11-12"


def test_copernicus_down_marks_stale(tmp_repo, mocked):
    _write_prev(tmp_repo, PREVIOUS)
    cold_weather(mocked)
    client = FakeClient(fail=SourceUnavailable("copernicus", "boom"))
    assert run(RUN, tmp_repo, ENV, session(), client) == 1
    assert status_of(tmp_repo)["stale_since"] == "2025-11-11"
    assert ntfy_bodies(mocked, "ops-topic") == ["copernicus unavailable"]


def test_other_exception_pings_ops_and_reraises(tmp_repo, mocked):
    cold_weather(mocked)
    client = FakeClient(fail=RuntimeError("secret detail"))
    with pytest.raises(RuntimeError):
        run(RUN, tmp_repo, ENV, session(), client)
    assert ntfy_bodies(mocked, "ops-topic") == ["RuntimeError"]


def test_baseline_cached(tmp_repo, mocked):
    cold_weather(mocked)
    first = FakeClient(s1=[S1Obs(SEASON_START - timedelta(days=5), -20.0)])
    assert run(RUN, tmp_repo, ENV, session(), first) == 0
    assert len(first.baseline_calls()) == 1
    baselines = json.loads((tmp_repo / "state/baselines.json").read_text(encoding="utf-8"))
    assert baselines == {"w1:2025-10-01": -20.0}
    second = FakeClient()
    assert run(RUN, tmp_repo, ENV, session(), second) == 0
    assert second.baseline_calls() == []


def test_budget_exhausted_skips_imagery(tmp_repo, mocked):
    cold_weather(mocked)
    (tmp_repo / "state").mkdir()
    (tmp_repo / "state/usage.json").write_text(json.dumps({"month": "2025-11", "used": 9000}),
                                               encoding="utf-8")
    client = FakeClient()
    assert run(RUN, tmp_repo, ENV, session(), client) == 0
    assert client.calls == []
    lake = status_of(tmp_repo)["lakes"]["w1"]
    assert lake["label"] == "unknown"  # thick, snow-free, but no imagery: weather only
    assert lake["thumb"] is None


def test_no_cdse_credentials_runs_weather_only(tmp_repo, mocked):
    cold_weather(mocked)
    assert run(RUN, tmp_repo, ENV, session()) == 0
    assert status_of(tmp_repo)["lakes"]["w1"]["label"] == "unknown"


def test_lake_without_interior_gets_no_imagery(tmp_repo, mocked):
    (tmp_repo / "site/data/lakes.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": [_feature("w1", 120.0, interior=None)]}),
        encoding="utf-8")
    cold_weather(mocked)
    client = FakeClient()
    assert run(RUN, tmp_repo, ENV, session(), client) == 0
    assert client.calls == []
    assert status_of(tmp_repo)["lakes"]["w1"]["label"] == "unknown"


def test_thumbnail_written_once_per_clear_day(tmp_repo, mocked):
    cold_weather(mocked)
    first = FakeClient()
    assert run(RUN, tmp_repo, ENV, session(), first) == 0
    assert [c for c in first.calls if c[0] == "png"] == [("png", RUN - timedelta(days=1),
                                                          RUN - timedelta(days=1))]
    assert (tmp_repo / "site/data/thumbs/w1.png").read_bytes() == b"\x89PNG fake"
    assert status_of(tmp_repo)["lakes"]["w1"]["thumb"] == "thumbs/w1.png"
    second = FakeClient()
    assert run(RUN, tmp_repo, ENV, session(), second) == 0
    assert [c for c in second.calls if c[0] == "png"] == []


def test_alert_send_failure_writes_status_pings_ops_keeps_labels(tmp_repo):
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        cold_weather(rsps)
        rsps.add(responses_lib.POST, ALERTS_URL, status=503)
        rsps.add(responses_lib.POST, OPS_URL, status=200)
        assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 1
        status = status_of(tmp_repo)
        assert status["stale_since"] is None
        assert status["lakes"]["w1"]["label"] == "likely_black_ice"
        assert ntfy_bodies(rsps, "ops-topic") == ["ntfy unavailable"]
        assert not (tmp_repo / "state/labels.json").exists()
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        cold_weather(rsps)
        rsps.add(responses_lib.POST, ALERTS_URL, status=200)
        assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
        assert ntfy_calls(rsps, "alerts-topic") == 1  # retried the next run


def test_ntfy_session_does_not_retry():
    s = run_daily.ntfy_session()
    assert s.get_adapter("https://ntfy.sh").max_retries.total == 0


def test_ops_ping_writes_marker_when_configured(tmp_repo, mocked, tmp_path):
    marker = tmp_path / "ops_notified"
    mocked.add(responses_lib.GET, ARCHIVE_URL, status=500)
    env = {**ENV, "WILDICE_OPS_MARKER": str(marker)}
    assert run(RUN, tmp_repo, env, session(), FakeClient()) == 1
    assert marker.exists()


def test_ops_ping_no_marker_when_unset(tmp_repo, mocked, tmp_path):
    mocked.add(responses_lib.GET, ARCHIVE_URL, status=500)
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 1
    assert not any(p.name == "ops_notified" for p in tmp_path.rglob("*"))


def test_failed_ops_ping_writes_no_marker(tmp_repo, tmp_path):
    marker = tmp_path / "ops_notified"
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses_lib.GET, ARCHIVE_URL, status=500)
        rsps.add(responses_lib.POST, OPS_URL, status=500)
        env = {**ENV, "WILDICE_OPS_MARKER": str(marker)}
        assert run(RUN, tmp_repo, env, session(), FakeClient()) == 1
    assert not marker.exists()


def test_logs_budget_usage(tmp_repo, mocked, caplog):
    caplog.set_level(logging.INFO)
    cold_weather(mocked)
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
    assert "requests used 0/9000" in caplog.text


def test_missing_alerts_topic_pings_ops_and_keeps_labels(tmp_repo, mocked):
    cold_weather(mocked)
    env = {"NTFY_TOPIC_OPS": "ops-topic"}
    assert run(RUN, tmp_repo, env, session(), FakeClient()) == 1
    assert ntfy_bodies(mocked, "ops-topic") == ["alerts topic not configured"]
    assert not (tmp_repo / "state/labels.json").exists()
    assert status_of(tmp_repo)["lakes"]["w1"]["label"] == "likely_black_ice"


def test_missing_alerts_topic_without_new_lakes_is_fine(tmp_repo, mocked):
    cold_weather(mocked, t_mean=5.0)  # open water: nothing to alert
    env = {"NTFY_TOPIC_OPS": "ops-topic"}
    assert run(RUN, tmp_repo, env, session(), FakeClient()) == 0
    assert ntfy_calls(mocked, "ops-topic") == 0


def test_other_exception_writes_stale_before_ops_ping(tmp_repo, mocked):
    _write_prev(tmp_repo, PREVIOUS)
    cold_weather(mocked)
    seen = {}
    real_ping = run_daily._ping_ops

    def spy(env, body, ntfy):
        seen["stale_at_ping"] = status_of(tmp_repo).get("stale_since")
        real_ping(env, body, ntfy)

    import unittest.mock as um
    with um.patch.object(run_daily, "_ping_ops", spy):
        with pytest.raises(RuntimeError):
            run(RUN, tmp_repo, ENV, session(), FakeClient(fail=RuntimeError("x")))
    assert seen["stale_at_ping"] == "2025-11-11"
    status = status_of(tmp_repo)
    assert status["stale_since"] == "2025-11-11" and status["lakes"] == PREVIOUS["lakes"]
    assert ntfy_bodies(mocked, "ops-topic") == ["RuntimeError"]


def test_weather_fetched_at_largest_lake_in_cell(tmp_repo, mocked):
    from urllib.parse import parse_qs, urlparse
    small = _feature("w1", 120.0)
    small["properties"].update(lat=61.02, lon=-149.53)
    big = _feature("w2", 300.0)
    big["properties"].update(lat=60.98, lon=-149.47)
    (tmp_repo / "site/data/lakes.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": [small, big]}), encoding="utf-8")
    cold_weather(mocked)
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
    wx_calls = [c for c in mocked.calls
                if c.request.url.startswith((ARCHIVE_URL, FORECAST_URL))]
    assert len(wx_calls) == 2
    for c in wx_calls:
        q = parse_qs(urlparse(c.request.url).query)
        assert (q["latitude"], q["longitude"]) == (["60.98"], ["-149.47"])
    assert (tmp_repo / "state/weather/61.0_-149.5.json").exists()


def test_days_left_in_month_includes_today():
    assert run_daily.days_left_in_month(date(2025, 11, 12)) == 19
    assert run_daily.days_left_in_month(date(2025, 11, 30)) == 1
    assert run_daily.days_left_in_month(date(2025, 12, 1)) == 31
    assert run_daily.days_left_in_month(date(2028, 2, 1)) == 29


def _two_lakes(root):
    (root / "site/data/lakes.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [_feature("w1", 120.0), _feature("w2", 300.0)]}), encoding="utf-8")


def test_imagery_paced_over_rest_of_month(tmp_repo, mocked):
    _two_lakes(tmp_repo)
    (tmp_repo / "state").mkdir()
    # 38 left on Nov 12 with 19 days to go: 2 requests today -> one lake (the larger)
    (tmp_repo / "state/usage.json").write_text(
        json.dumps({"month": "2025-11", "used": 9000 - 38}), encoding="utf-8")
    cold_weather(mocked)
    client = FakeClient()
    assert run(RUN, tmp_repo, ENV, session(), client) == 0
    assert len([c for c in client.calls if c[0] == "s2"]) == 1
    lakes = status_of(tmp_repo)["lakes"]
    assert lakes["w2"]["label"] == "likely_black_ice" and lakes["w1"]["label"] == "unknown"


def test_hidden_lake_not_imaged(tmp_repo, mocked):
    _two_lakes(tmp_repo)
    (tmp_repo / "prefs").mkdir()
    (tmp_repo / "prefs/1.json").write_text(json.dumps({"lake_id": "w2", "action": "hide"}),
                                           encoding="utf-8")
    cold_weather(mocked)
    client = FakeClient()
    assert run(RUN, tmp_repo, ENV, session(), client) == 0
    assert len([c for c in client.calls if c[0] == "s2"]) == 1
    assert status_of(tmp_repo)["lakes"]["w1"]["label"] == "likely_black_ice"


class FailFirstLake(FakeClient):
    """The first lake imaged (the largest) fails with `exc`; the rest succeed."""

    def __init__(self, exc):
        super().__init__()
        self.exc = exc
        self.failed = False

    def s2_stats(self, geometry, start, end):
        if not self.failed:
            self.failed = True
            self.calls.append(("s2", start, end))
            raise self.exc
        return super().s2_stats(geometry, start, end)


def test_one_lake_client_error_skips_only_that_lake(tmp_repo, mocked, caplog):
    caplog.set_level(logging.INFO)
    _two_lakes(tmp_repo)  # w2 is larger, so imaged first
    cold_weather(mocked)
    client = FailFirstLake(SourceUnavailable("copernicus", "400 Client Error", status=400))
    assert run(RUN, tmp_repo, ENV, session(), client) == 0
    lakes = status_of(tmp_repo)["lakes"]
    assert lakes["w2"]["label"] == "unknown"  # no imagery for it today
    assert lakes["w1"]["label"] == "likely_black_ice"
    assert status_of(tmp_repo)["stale_since"] is None
    assert ntfy_calls(mocked, "ops-topic") == 0
    assert "w2" in caplog.text and "400" in caplog.text
    assert "400 Client Error" not in caplog.text  # id + status only


@pytest.mark.parametrize("status", [401, 403, 429, 500, None])
def test_auth_rate_limit_or_server_error_still_fails_run(tmp_repo, mocked, status):
    _write_prev(tmp_repo, PREVIOUS)
    _two_lakes(tmp_repo)
    cold_weather(mocked)
    client = FailFirstLake(SourceUnavailable("copernicus", "boom", status=status))
    assert run(RUN, tmp_repo, ENV, session(), client) == 1
    assert status_of(tmp_repo)["stale_since"] == "2025-11-11"
    assert ntfy_bodies(mocked, "ops-topic") == ["copernicus unavailable"]


# --- season S2 history (clearings older than the 14-day lookback) ---

def _season_daily(end, snow_on=None):
    """Cold days from season start to `end`; `snow_on` = {date: cm}."""
    snow_on = snow_on or {}
    days = [SEASON_START + timedelta(days=i) for i in range((end - SEASON_START).days + 1)]
    n = len(days)
    return {"latitude": 61.0, "longitude": -149.5, "daily": {
        "time": [d.isoformat() for d in days],
        "temperature_2m_min": [-8.0] * n, "temperature_2m_max": [-2.0] * n,
        "temperature_2m_mean": [-5.0] * n,
        "snowfall_sum": [snow_on.get(d, 0.0) for d in days],
        "rain_sum": [0.0] * n, "wind_gusts_10m_max": [10.0] * n}}


def _run_with_weather(root, day, client, env=ENV, snow_on=None):
    with responses_lib.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        for url in (ARCHIVE_URL, FORECAST_URL):
            rsps.add(responses_lib.GET, url, json=[_season_daily(day, snow_on)], status=200)
        rsps.add(responses_lib.POST, ALERTS_URL, status=200)
        rsps.add(responses_lib.POST, OPS_URL, status=200)
        return run(day, root, env, session(), client)


def _no_december_low_sun(root, pinned="[w1]"):
    import re
    text = (root / "config.yaml").read_text(encoding="utf-8")
    text = re.sub(r'low_sun_start: "[^"]*"', 'low_sun_start: "01-20"', text)
    text = re.sub(r'low_sun_end: "[^"]*"', 'low_sun_end: "01-25"', text)
    text = text.replace("pinned: []", f"pinned: {pinned}")
    (root / "config.yaml").write_text(text, encoding="utf-8")


DEC1, DEC5, DEC20 = date(2025, 12, 1), date(2025, 12, 5), date(2025, 12, 20)
DARK_DEC5 = S2Obs(DEC5, 0.95, 0.05, 0.05, 0.02)


@pytest.mark.parametrize("dec20_client", ["none", "no_new_image"])
def test_clearing_remembered_past_lookback(tmp_repo, dec20_client):
    """Dec 1 snow 5 cm, Dec 5 dark image -> Dec 20 with no new image: still black ice."""
    _no_december_low_sun(tmp_repo)  # Dec 5 must not fall in the low-sun window
    snow = {DEC1: 5.0}
    assert _run_with_weather(tmp_repo, DEC5, FakeClient(s2=[DARK_DEC5]), snow_on=snow) == 0
    assert status_of(tmp_repo)["lakes"]["w1"]["label"] == "likely_black_ice"
    hist = json.loads((tmp_repo / "state/s2_history.json").read_text(encoding="utf-8"))
    assert hist == {"w1": {"2025-12-05": "dark"}}

    client = None if dec20_client == "none" else FakeClient(s2=[])
    env = {k: v for k, v in ENV.items()}  # no CDSE creds: weather + history only
    assert _run_with_weather(tmp_repo, DEC20, client, env=env, snow_on=snow) == 0
    w1 = status_of(tmp_repo)["lakes"]["w1"]
    assert w1["label"] == "likely_black_ice"
    assert w1["last_clear_day"] == "2025-12-05"
    assert "dark on Dec 5 image" in w1["reason"]


def test_s2_history_drops_previous_season(tmp_repo, mocked):
    cold_weather(mocked)
    (tmp_repo / "state").mkdir()
    (tmp_repo / "state/s2_history.json").write_text(json.dumps(
        {"w1": {"2025-03-01": "dark", "2025-10-20": "white"}, "w9": {"2025-02-01": "grey"}}),
        encoding="utf-8")
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
    hist = json.loads((tmp_repo / "state/s2_history.json").read_text(encoding="utf-8"))
    assert hist == {"w1": {"2025-10-20": "white", "2025-11-11": "dark"}}


def test_corrupt_s2_history_is_ignored(tmp_repo, mocked):
    cold_weather(mocked)
    (tmp_repo / "state").mkdir()
    (tmp_repo / "state/s2_history.json").write_text(
        json.dumps({"w1": {"bad-date": "dark", "2025-11-01": "purple"}, "w2": 3}),
        encoding="utf-8")
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
    hist = json.loads((tmp_repo / "state/s2_history.json").read_text(encoding="utf-8"))
    assert hist == {"w1": {"2025-11-11": "dark"}}


def test_last_checked_records_imaged_lakes_and_drops_old_season(tmp_repo, mocked):
    cold_weather(mocked)
    (tmp_repo / "state").mkdir()
    (tmp_repo / "state/last_checked.json").write_text(
        json.dumps({"w9": "2025-02-01", "w1": "2025-10-20", "bad": "not-a-date"}),
        encoding="utf-8")
    assert run(RUN, tmp_repo, ENV, session(), FakeClient()) == 0
    checked = json.loads((tmp_repo / "state/last_checked.json").read_text(encoding="utf-8"))
    assert checked == {"w1": RUN.isoformat()}


def test_last_checked_untouched_without_imagery(tmp_repo, mocked):
    cold_weather(mocked)
    env = {k: v for k, v in ENV.items() if not k.startswith("CDSE")}
    assert run(RUN, tmp_repo, env, session(), None) == 0
    path = tmp_repo / "state/last_checked.json"
    assert not path.exists() or json.loads(path.read_text(encoding="utf-8")) == {}
