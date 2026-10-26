import json
from datetime import date
from pathlib import Path

import pytest
import requests
import responses

from wildice.config import load_config
from wildice.imagery import (
    PROCESS_URL, STATS_URL, TOKEN_URL, Budget, CopernicusClient, fetch_imagery,
    s1_baseline,
)
from wildice.models import Lake, S2Obs, SourceUnavailable
from wildice.weather import make_session

FIX = Path(__file__).parent / "fixtures"
cfg = load_config(Path("config.yaml"))
GEOM = {"type": "Polygon",
        "coordinates": [[[-150.0, 61.0], [-149.9, 61.0], [-149.9, 61.1], [-150.0, 61.0]]]}
D1, D2 = date(2025, 11, 1), date(2025, 11, 14)


def fixture(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def add_token(expires_in=600):
    responses.add(responses.POST, TOKEN_URL, status=200,
                  json={"access_token": "tok", "expires_in": expires_in})


@pytest.fixture
def client():
    return CopernicusClient("id", "secret", make_session())


@responses.activate
def test_s2_parse(client):
    add_token()
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s2_stats.json"))
    obs = client.s2_stats(GEOM, D1, D2)
    assert obs[0] == S2Obs(date(2025, 11, 3), 0.92, 0.051, 0.043, 0.020)
    assert obs[1].day == date(2025, 11, 8)
    assert obs[1].valid_fraction == pytest.approx(0.4)
    assert obs[1].b03 == pytest.approx(0.056)


@responses.activate
def test_s2_request_shape(client):
    add_token()
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s2_empty.json"))
    client.s2_stats(GEOM, D1, D2)
    req = responses.calls[1].request
    body = json.loads(req.body)
    assert req.headers["Authorization"] == "Bearer tok"
    assert body["input"]["bounds"]["geometry"] == GEOM
    assert body["input"]["bounds"]["properties"]["crs"] == \
        "http://www.opengis.net/def/crs/EPSG/0/4326"
    assert body["input"]["data"][0]["type"] == "sentinel-2-l2a"
    agg = body["aggregation"]
    assert agg["aggregationInterval"] == {"of": "P1D"}
    assert agg["timeRange"] == {"from": "2025-11-01T00:00:00Z",
                                "to": "2025-11-15T00:00:00Z"}
    assert "SCL" in agg["evalscript"]


@responses.activate
def test_s2_no_valid_pixels_gives_zero_valid_fraction(client):
    add_token()
    data = fixture("cdse_s2_stats.json")
    for out in data["data"][0]["outputs"].values():
        for b in out["bands"].values():
            b["stats"]["mean"] = 0.0
    responses.add(responses.POST, STATS_URL, json=data)
    obs = client.s2_stats(GEOM, D1, D2)
    assert obs[0] == S2Obs(date(2025, 11, 3), 0.0, 0.0, 0.0, 0.0)
    assert obs[1].valid_fraction == pytest.approx(0.4)


@responses.activate
def test_s2_nan_intervals_are_skipped(client):
    add_token()
    data = fixture("cdse_s2_stats.json")
    for row in data["data"]:
        row["outputs"]["valid"]["bands"]["B0"]["stats"]["mean"] = "NaN"
    responses.add(responses.POST, STATS_URL, json=data)
    assert client.s2_stats(GEOM, D1, D2) == []


@pytest.mark.parametrize("name,ids", [("s1_stats.js", ["vv"]),
                                      ("s2_stats.js", ["reflectance", "valid"])])
def test_evalscripts_declare_float32(name, ids):
    import re
    text = (Path(__file__).parents[1] / "wildice" / "evalscripts" / name).read_text(
        encoding="utf-8")
    for oid in ids:
        assert re.search(r'id:\s*"%s"[^}]*sampleType:\s*"FLOAT32"' % oid, text), oid


def test_s1_polarization_constant():
    from wildice import imagery
    assert imagery.S1_POLARIZATION == "DV"


@responses.activate
def test_s2_empty_is_empty_list(client):
    add_token()
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s2_empty.json"))
    assert client.s2_stats(GEOM, D1, D2) == []


@responses.activate
def test_s1_db_conversion(client):
    add_token()
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s1_stats.json"))
    obs = client.s1_stats(GEOM, D1, D2)
    assert obs[0].day == date(2025, 11, 4)
    assert obs[0].vv_db == pytest.approx(-20.0)
    assert obs[1].vv_db == pytest.approx(-16.9897, abs=1e-3)
    body = json.loads(responses.calls[1].request.body)
    assert body["input"]["data"][0]["type"] == "sentinel-1-grd"


@responses.activate
def test_s1_skips_nonpositive_and_nan(client):
    add_token()
    data = fixture("cdse_s1_stats.json")
    data["data"][0]["outputs"]["vv"]["bands"]["B0"]["stats"]["mean"] = 0.0
    data["data"][1]["outputs"]["vv"]["bands"]["B0"]["stats"]["mean"] = "NaN"
    responses.add(responses.POST, STATS_URL, json=data)
    assert client.s1_stats(GEOM, D1, D2) == []


@responses.activate
def test_token_reused(client):
    add_token()
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s2_empty.json"))
    client.s2_stats(GEOM, D1, D2)
    client.s2_stats(GEOM, D1, D2)
    assert len([c for c in responses.calls if c.request.url == TOKEN_URL]) == 1


@responses.activate
def test_token_refreshed_after_expiry():
    now = [0.0]
    c = CopernicusClient("id", "secret", make_session(), clock=lambda: now[0])
    add_token(expires_in=600)
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s2_empty.json"))
    c.s2_stats(GEOM, D1, D2)
    now[0] = 1000.0
    c.s2_stats(GEOM, D1, D2)
    assert len([x for x in responses.calls if x.request.url == TOKEN_URL]) == 2


@responses.activate
def test_http_500_raises_source_unavailable():
    c = CopernicusClient("id", "secret", requests.Session())  # no retries
    add_token()
    responses.add(responses.POST, STATS_URL, status=500)
    with pytest.raises(SourceUnavailable):
        c.s2_stats(GEOM, D1, D2)


@responses.activate
def test_token_failure_raises_source_unavailable(client):
    responses.add(responses.POST, TOKEN_URL, status=401)
    with pytest.raises(SourceUnavailable):
        client.s2_stats(GEOM, D1, D2)


@responses.activate
def test_bad_json_raises_source_unavailable(client):
    add_token()
    responses.add(responses.POST, STATS_URL, json={"unexpected": 1})
    with pytest.raises(SourceUnavailable):
        client.s2_stats(GEOM, D1, D2)


@responses.activate
def test_truecolor_png(client):
    add_token()
    responses.add(responses.POST, PROCESS_URL, body=b"\x89PNG-bytes",
                  content_type="image/png")
    assert client.truecolor_png(GEOM, date(2025, 11, 3)) == b"\x89PNG-bytes"
    body = json.loads(responses.calls[1].request.body)
    assert body["output"]["width"] == 256 and body["output"]["height"] == 256
    assert body["output"]["responses"][0]["format"]["type"] == "image/png"
    assert body["input"]["data"][0]["type"] == "sentinel-2-l2a"


def test_budget_resets_monthly(tmp_path):
    p = tmp_path / "budget.json"
    p.write_text(json.dumps({"month": "2025-10", "used": 8000}), encoding="utf-8")
    b = Budget(p, 9000, today=lambda: date(2025, 11, 2))
    assert b.remaining() == 9000
    p2 = tmp_path / "b2.json"
    p2.write_text(json.dumps({"month": "2025-11", "used": 100}), encoding="utf-8")
    assert Budget(p2, 9000, today=lambda: date(2025, 11, 2)).remaining() == 8900


def test_budget_missing_or_corrupt_file(tmp_path):
    assert Budget(tmp_path / "nope.json", 50).remaining() == 50
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert Budget(bad, 50).remaining() == 50


def test_budget_save_roundtrip_and_floor(tmp_path):
    p = tmp_path / "sub" / "budget.json"

    def t():
        return date(2025, 11, 2)

    b = Budget(p, 3, today=t)
    b.record(5)
    assert b.remaining() == 0
    b.save()
    assert Budget(p, 3, today=t).remaining() == 0
    assert "\r" not in p.read_bytes().decode("utf-8")


@responses.activate
def test_budget_counts_requests(tmp_path, client):
    add_token()
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s2_empty.json"))
    client.budget = Budget(tmp_path / "b.json", 100)
    client.s2_stats(GEOM, D1, D2)
    client.s1_stats(GEOM, D1, D2)
    assert client.budget.remaining() == 98


def make_lake(interior=GEOM):
    return Lake(id="w1", name="X", area_acres=50, road_mi=1, trail_mi=None,
                lat=61.0, lon=-150.0, interior=interior, warning=None)


def test_fetch_imagery_rejects_missing_interior(client):
    with pytest.raises(ValueError):
        fetch_imagery(client, make_lake(None), date(2025, 11, 14), cfg, None)


@responses.activate
def test_fetch_imagery_window_and_assembly(client):
    add_token()
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s2_stats.json"))
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s1_stats.json"))
    run = date(2025, 11, 14)
    stats = fetch_imagery(client, make_lake(), run, cfg, -18.5)
    assert len(stats.s2) == 2 and isinstance(stats.s2, tuple)
    assert len(stats.s1) == 2 and isinstance(stats.s1, tuple)
    assert stats.s1_baseline_db == -18.5
    tr = json.loads(responses.calls[1].request.body)["aggregation"]["timeRange"]
    assert tr["from"] == "2025-10-31T00:00:00Z"  # 14 days back
    assert tr["to"] == "2025-11-15T00:00:00Z"


@responses.activate
def test_s1_baseline_median(client):
    add_token()
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s1_stats.json"))
    base = s1_baseline(client, make_lake(), date(2025, 11, 20))
    assert base == pytest.approx((-20.0 + -16.9897) / 2, abs=1e-3)
    tr = json.loads(responses.calls[1].request.body)["aggregation"]["timeRange"]
    assert tr["from"] == "2025-10-21T00:00:00Z"
    assert tr["to"] == "2025-11-20T00:00:00Z"  # freeze_up day excluded


@responses.activate
def test_s1_baseline_none_when_empty(client):
    add_token()
    responses.add(responses.POST, STATS_URL, json=fixture("cdse_s2_empty.json"))
    assert s1_baseline(client, make_lake(), date(2025, 11, 20)) is None


class _Raw:
    def __init__(self, history):
        self.retries = type("R", (), {"history": history})()


def test_attempts_counts_retry_history():
    from types import SimpleNamespace
    from wildice.imagery import _attempts
    assert _attempts(SimpleNamespace(raw=_Raw([1, 2]))) == 3
    assert _attempts(SimpleNamespace(raw=object())) == 1
    assert _attempts(SimpleNamespace(raw=SimpleNamespace(retries=None))) == 1
    assert _attempts(SimpleNamespace()) == 1


@responses.activate
def test_failed_call_still_records_one(tmp_path):
    c = CopernicusClient("id", "secret", requests.Session(),
                         budget=Budget(tmp_path / "b.json", 100))
    add_token()
    responses.add(responses.POST, STATS_URL, status=500)
    with pytest.raises(SourceUnavailable):
        c.s2_stats(GEOM, D1, D2)
    assert c.budget.remaining() == 99


@responses.activate
def test_s2_nan_band_on_valid_day_is_skipped(client):
    add_token()
    data = fixture("cdse_s2_stats.json")
    data["data"][0]["outputs"]["reflectance"]["bands"]["B1"]["stats"]["mean"] = "NaN"
    responses.add(responses.POST, STATS_URL, json=data)
    obs = client.s2_stats(GEOM, D1, D2)
    assert [o.day for o in obs] == [date(2025, 11, 8)]


def test_source_unavailable_status_defaults_none():
    assert SourceUnavailable("copernicus").status is None
    assert SourceUnavailable("copernicus", "x", status=400).status == 400


@pytest.mark.parametrize("code", [400, 404, 422, 401, 403, 429, 500])
@responses.activate
def test_http_error_carries_status_without_secrets(code):
    c = CopernicusClient("id-SECRET1", "cs-SECRET2", requests.Session())  # no retries
    responses.add(responses.POST, TOKEN_URL, status=200,
                  json={"access_token": "tok-SECRET3", "expires_in": 600})
    responses.add(responses.POST, STATS_URL, status=code)
    with pytest.raises(SourceUnavailable) as ei:
        c.s2_stats(GEOM, D1, D2)
    assert ei.value.status == code
    assert "SECRET" not in str(ei.value)


@responses.activate
def test_token_http_error_carries_status():
    c = CopernicusClient("id", "cs-SECRET2", requests.Session())
    responses.add(responses.POST, TOKEN_URL, status=401)
    with pytest.raises(SourceUnavailable) as ei:
        c.s2_stats(GEOM, D1, D2)
    assert ei.value.status == 401 and "SECRET" not in str(ei.value)


@responses.activate
def test_retries_exhausted_has_no_status():
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=1, backoff_factor=0, status_forcelist=[503], allowed_methods=None)))
    c = CopernicusClient("id", "secret", s)
    add_token()
    responses.add(responses.POST, STATS_URL, status=503)
    with pytest.raises(SourceUnavailable) as ei:
        c.s2_stats(GEOM, D1, D2)  # urllib3 retries, then RetryError
    assert ei.value.status is None
