from datetime import date, timedelta
from pathlib import Path

import pytest
import requests
import responses

from wildice import alert
from wildice.config import load_config
from wildice.icelog import Export, fetch_export, reports_from_export
from wildice.models import Confidence, IceState, Label, Lake, Score
from wildice.prefs import load_prefs
from wildice.reports import Report, apply_report

REPO = Path(__file__).resolve().parent.parent
CFG = load_config(REPO / "config.yaml")
RUN = date(2026, 11, 20)
SEASON = date(2026, 10, 1)
URL = "https://ice.example"
# ~1.1 km x 0.5 km lake near Anchorage
POLY = {"type": "Polygon", "coordinates": [[[-149.51, 60.99], [-149.49, 60.99], [-149.49, 61.0],
                                             [-149.51, 61.0], [-149.51, 60.99]]]}
LAKES = {"w1": Lake("w1", "Test", 200.0, 0.1, None, 60.995, -149.5, POLY, None)}


def row(**kw):
    base = {"id": "r1", "lake_id": "w1", "day": "2026-11-19", "created_at": "2026-11-19T20:00:00Z",
            "rating": "skated", "grade": "B+", "note": "", "lat": None, "lon": None,
            "gps_source": None, "role": "friend"}
    return {**base, **kw}


# --- fetching -------------------------------------------------------------------

@responses.activate
def test_fetch_export_parses():
    responses.add(responses.GET, f"{URL}/api/export", json={
        "reports": [row()], "prefs": [{"lake_id": "w1", "action": "pin", "created_at": "x"}],
        "pending": {"comments": 3, "photos": 2}})
    e = fetch_export(URL, "tok", SEASON, requests.Session())
    assert e == Export([row()], [{"lake_id": "w1", "action": "pin", "created_at": "x"}], 3, 2)
    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Bearer tok" and "since=2026-10-01" in req.url


@responses.activate
@pytest.mark.parametrize("kind", ["500", "bad json", "down"])
def test_export_failure_returns_none(kind, caplog):
    if kind == "500":
        responses.add(responses.GET, f"{URL}/api/export", status=500)
    elif kind == "bad json":
        responses.add(responses.GET, f"{URL}/api/export", body="<html>")
    assert fetch_export(URL, "tok", SEASON, requests.Session()) is None
    assert "tok" not in caplog.text
    if kind == "500":
        assert "HTTP 500" in caplog.text


# --- turning rows into reports --------------------------------------------------

def test_off_lake_friend_report_ignored_owner_never_checked():
    far = dict(lat=61.2, lon=-149.9, gps_source="photo")  # ~25 km away
    got = reports_from_export([row(**far)], LAKES, RUN, SEASON, CFG)
    assert got == {}
    got = reports_from_export([row(role="owner", **far)], LAKES, RUN, SEASON, CFG)
    assert got["w1"].source == "owner" and got["w1"].verified == "ok"


def test_on_lake_and_no_gps_friend_reports_used():
    on = reports_from_export([row(lat=60.995, lon=-149.5, gps_source="device")], LAKES, RUN, SEASON, CFG)
    assert on["w1"] == Report(date(2026, 11, 19), "skated", "", grade="B+", source="friend",
                              verified="ok", week_count=1)
    shore = reports_from_export([row(lat=61.0015, lon=-149.5, gps_source="photo")], LAKES, RUN, SEASON, CFG)
    assert shore["w1"].verified == "ok"  # ~170 m from the outline: within 300 m
    none = reports_from_export([row()], LAKES, RUN, SEASON, CFG)
    assert none["w1"].verified == "no_gps"


def test_newest_wins_and_week_count():
    rows = [row(id="a", day="2026-11-10", created_at="2026-11-10T10:00:00Z", rating="water", grade=None),
            row(id="b", day="2026-11-18", created_at="2026-11-18T10:00:00Z"),
            row(id="c", day="2026-11-19", created_at="2026-11-19T10:00:00Z", grade="A-"),
            row(id="d", day="2026-11-19", created_at="2026-11-19T09:00:00Z", lake_id="w404")]
    got = reports_from_export(rows, LAKES, RUN, SEASON, CFG)
    assert set(got) == {"w1"}  # unknown lake dropped
    assert got["w1"].grade == "A-" and got["w1"].week_count == 2


def test_last_season_rows_dropped():
    assert reports_from_export([row(day="2026-03-01")], LAKES, RUN, SEASON, CFG) == {}


# --- grades in the label --------------------------------------------------------

def _score(label=Label.UNKNOWN):
    return Score("w1", label, Confidence.MEDIUM, "~25 cm est.", 25.0, None)


def _ice():
    return IceState(500, 25, date(2026, 10, 20), None, 0.0, None, ())


def _rep(rating="skated", grade=None, source="friend", note="", week=1):
    return Report(date(2026, 11, 19), rating, note, grade=grade, source=source, week_count=week)


def test_good_grade_skated_is_black_ice_and_names_grade():
    sc = apply_report(_score(), _rep(grade="B+"), _ice(), {}, RUN, CFG)
    assert sc.label is Label.LIKELY_BLACK_ICE and sc.confidence is Confidence.HIGH
    assert sc.reason.startswith("Reported skateable ice on Nov 19 (B+); ")


def test_c_minus_is_still_good_d_plus_is_rough():
    assert apply_report(_score(), _rep(grade="C-"), _ice(), {}, RUN, CFG).label is Label.LIKELY_BLACK_ICE
    assert apply_report(_score(), _rep(grade="D+"), _ice(), {}, RUN, CFG).label is Label.ROUGH_ICE


def test_d_skated_is_rough_and_does_not_alert():
    sc = apply_report(_score(), _rep(grade="D"), _ice(), {}, RUN, CFG)
    assert sc.label is Label.ROUGH_ICE
    lake = LAKES["w1"]
    assert alert.newly_black_ice({"w1": sc}, {}, {"w1": lake}, frozenset(), frozenset()) == []


def test_rough_with_any_grade_is_rough_ice():
    assert apply_report(_score(), _rep("rough", "A+"), _ice(), {}, RUN, CFG).label is Label.ROUGH_ICE


def test_notes_never_published():
    sc = apply_report(_score(), _rep(grade="B", note="east end glassy"), _ice(), {}, RUN, CFG)
    assert "glassy" not in sc.reason
    sc = apply_report(_score(), _rep(grade="B", source="owner", note="east end glassy"), _ice(), {}, RUN, CFG)
    assert sc.reason.startswith("You reported skateable ice on Nov 19 (B); ")  # notes are never public
    assert "glassy" not in sc.reason


def test_three_reports_this_week_noted():
    sc = apply_report(_score(), _rep(grade="A", week=3), _ice(), {}, RUN, CFG)
    assert "; 3 reports this week" in sc.reason


# --- prefs and the morning alert -------------------------------------------------

def test_export_prefs_pin_a_lake(tmp_path):
    pinned, hidden = load_prefs(CFG, tmp_path / "none",
                                extra=[{"lake_id": "w9", "action": "pin"},
                                       {"lake_id": "w8", "action": "hide"},
                                       {"lake_id": "w8", "action": "unhide"}])
    assert "w9" in pinned and "w8" not in hidden


def test_pending_line_only_when_something_waits():
    sc = {"w1": _score(Label.LIKELY_BLACK_ICE)}
    _, body, _ = alert.format_alert(["w1"], LAKES, sc, frozenset(), "https://x", pending=(3, 2))
    assert body.endswith("\n\n3 comments, 2 photos waiting")
    _, body, _ = alert.format_alert(["w1"], LAKES, sc, frozenset(), "https://x", pending=(1, 0))
    assert body.endswith("\n\n1 comment waiting")
    _, body, _ = alert.format_alert(["w1"], LAKES, sc, frozenset(), "https://x")
    assert "waiting" not in body


@responses.activate
def test_fetch_export_reads_featured_photos():
    feat = [{"lake_id": "w1", "public_id": "p1", "created_at": "2026-11-20T10:00:00Z"}]
    responses.add(responses.GET, f"{URL}/api/export", json={
        "reports": [], "prefs": [], "pending": {"comments": 0, "photos": 0}, "featured": feat})
    assert fetch_export(URL, "tok", SEASON, requests.Session()).featured == feat
