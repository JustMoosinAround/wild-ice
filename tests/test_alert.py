import pytest
import requests
import responses

from wildice.alert import (
    format_alert, load_labels, newly_black_ice, save_labels, send_ntfy,
)
from wildice.models import Confidence, Label, Lake, Score, SourceUnavailable

BASE = "https://example.github.io/wildice"


def lake(i, area=100.0, name=None):
    return Lake(id=i, name=name, area_acres=area, road_mi=1.0, trail_mi=None,
                lat=61.0, lon=-149.0, interior=None, warning=None)


def score(i, label=Label.LIKELY_BLACK_ICE, reason="clear, dark ice"):
    return Score(lake_id=i, label=label, confidence=Confidence.HIGH, reason=reason,
                 thickness_cm=12.0, last_clear_day=None)


NONE = frozenset()


def test_new_lake_alerts():
    lakes = {"w1": lake("w1")}
    assert newly_black_ice({"w1": score("w1")}, {"w1": "freezing"}, lakes, NONE, NONE) == ["w1"]


def test_absent_prev_alerts():
    lakes = {"w1": lake("w1")}
    assert newly_black_ice({"w1": score("w1")}, {}, lakes, NONE, NONE) == ["w1"]


def test_unchanged_lake_silent():
    lakes = {"w1": lake("w1")}
    assert newly_black_ice({"w1": score("w1")}, {"w1": "likely_black_ice"}, lakes, NONE, NONE) == []


def test_returns_after_leaving():
    lakes = {"w1": lake("w1")}
    assert newly_black_ice({"w1": score("w1")}, {"w1": "snow_covered"}, lakes, NONE, NONE) == ["w1"]


def test_non_black_ice_not_alerted():
    lakes = {"w1": lake("w1")}
    assert newly_black_ice({"w1": score("w1", Label.FREEZING)}, {}, lakes, NONE, NONE) == []


def test_hidden_never_alerts():
    lakes = {"w1": lake("w1")}
    assert newly_black_ice({"w1": score("w1")}, {}, lakes, NONE, frozenset({"w1"})) == []


def test_pinned_first():
    lakes = {"w1": lake("w1", 500), "w2": lake("w2", 50), "w3": lake("w3", 300)}
    scores = {i: score(i) for i in lakes}
    assert newly_black_ice(scores, {}, lakes, frozenset({"w2"}), NONE) == ["w2", "w1", "w3"]


def test_title_singular_and_plural():
    lakes = {"w1": lake("w1"), "w2": lake("w2")}
    scores = {i: score(i) for i in lakes}
    assert format_alert(["w1"], lakes, scores, NONE, BASE)[0] == "1 lake looks skateable"
    assert format_alert(["w1", "w2"], lakes, scores, NONE, BASE)[0] == "2 lakes look skateable"


def test_body_has_map_link_and_click():
    lakes = {"w1": lake("w1", name="Jewel Lake"), "w2": lake("w2")}
    scores = {i: score(i) for i in lakes}
    title, body, click = format_alert(["w1", "w2"], lakes, scores, frozenset({"w1"}), BASE)
    assert "/#lake=w1)" in body
    assert click == f"{BASE}/#lake=w1"
    assert body.splitlines()[0] == (
        "- ★ **Jewel Lake** — clear, dark ice ([map](https://example.github.io/wildice/#lake=w1))")
    assert body.splitlines()[1].startswith("- **Unnamed lake (100 ac)** — ")
    title.encode("latin-1")


@responses.activate
def test_send_ntfy_headers():
    responses.add(responses.POST, "https://ntfy.sh/topic123", status=200)
    send_ntfy("topic123", "2 lakes look skateable", "- ★ body", f"{BASE}/#lake=w1",
              requests.Session())
    req = responses.calls[0].request
    assert req.headers["Title"] == "2 lakes look skateable"
    assert req.headers["Markdown"] == "yes"
    assert req.headers["Click"] == f"{BASE}/#lake=w1"
    assert req.body.decode("utf-8") == "- ★ body"


@responses.activate
def test_send_ntfy_no_click():
    responses.add(responses.POST, "https://ntfy.sh/t", status=200)
    send_ntfy("t", "x", "y", None, requests.Session())
    assert "Click" not in responses.calls[0].request.headers


@responses.activate
def test_send_ntfy_failure_raises():
    responses.add(responses.POST, "https://ntfy.sh/t", status=500)
    with pytest.raises(SourceUnavailable) as ei:
        send_ntfy("t", "x", "y", None, requests.Session())
    assert ei.value.source == "ntfy"


def test_labels_roundtrip(tmp_path):
    p = tmp_path / "state" / "alert_state.json"
    save_labels(p, {"w1": score("w1"), "w2": score("w2", Label.SNOW_COVERED)})
    assert load_labels(p) == {"w1": "likely_black_ice", "w2": "snow_covered"}
    assert b"\r\n" not in p.read_bytes()


def test_load_labels_missing_or_corrupt(tmp_path):
    assert load_labels(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_labels(bad) == {}
