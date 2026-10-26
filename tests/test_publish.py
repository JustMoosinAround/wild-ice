import json
from datetime import date, timedelta

from wildice.models import Confidence, Label, Lake, Score
from wildice.publish import build_status, load_history, write_outputs

RUN = date(2025, 11, 12)
lake = Lake("w123", "Foo", 50, 1, None, 61.0, -149.0, None, "thin shore")
hist = {"w123": [{"day": "2025-11-11", "label": "freezing"}]}


def status(stale=None):
    sc = {"w123": Score("w123", Label.LIKELY_BLACK_ICE, Confidence.HIGH, "why", 12.0, date(2025, 11, 11))}
    return build_status([lake], sc, frozenset({"w123"}), frozenset(), hist, RUN, stale)


def test_status_schema(tmp_path):
    s = status()
    assert s["run_date"] == "2025-11-12" and s["stale_since"] is None
    assert s["disclaimer"] == "Rough estimate only — check ice yourself."
    e = s["lakes"]["w123"]
    assert set(e) == {"name", "label", "confidence", "reason", "thickness_cm", "last_clear_day",
                      "browser_url", "thumb", "pinned", "hidden", "warning", "history"}
    assert (e["name"], e["label"], e["confidence"], e["reason"]) == ("Foo", "likely_black_ice", "high", "why")
    assert e["thickness_cm"] == 12.0 and e["last_clear_day"] == "2025-11-11"
    assert "fromTime=2025-11-11" in e["browser_url"]
    assert e["pinned"] is True and e["hidden"] is False and e["warning"] == "thin shore"
    assert e["history"] == hist["w123"]
    site = tmp_path / "data"
    write_outputs(s, site, RUN)
    raw = (site / "status.json").read_bytes()
    assert b"\r\n" not in raw and "—".encode() in raw
    out = json.loads(raw)
    assert out["lakes"]["w123"]["thumb"] is None
    assert json.loads((site / "history" / "2025-11-12.json").read_text(encoding="utf-8")) == {"w123": "likely_black_ice"}


def test_thumb_only_when_file_exists(tmp_path):
    (tmp_path / "thumbs").mkdir()
    (tmp_path / "thumbs" / "w123.png").write_bytes(b"x")
    write_outputs(status(), tmp_path, RUN)
    assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["lakes"]["w123"]["thumb"] == "thumbs/w123.png"


def test_stale_since_written(tmp_path):
    write_outputs(status(date(2025, 11, 10)), tmp_path, RUN)
    assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["stale_since"] == "2025-11-10"


def test_history_window(tmp_path):
    h = tmp_path / "history"
    h.mkdir()
    for i in range(20):
        d = RUN - timedelta(days=i)
        (h / f"{d}.json").write_text(json.dumps({"w1": "freezing"}), encoding="utf-8")
    got = load_history(h, RUN)
    assert len(got["w1"]) == 14
    days = [x["day"] for x in got["w1"]]
    assert days == sorted(days) and days[-1] == "2025-11-12" and days[0] == "2025-10-30"
    assert load_history(tmp_path / "missing", RUN) == {}


def test_status_unnamed_lake_name():
    unnamed = Lake("w9", None, 34.2, 1, None, 61.0, -149.0, None, None)
    s = build_status([unnamed], {}, frozenset(), frozenset(), {}, RUN, None)
    assert s["lakes"]["w9"]["name"] == "Unnamed lake (34 ac)"


def test_thickness_rounded_to_whole_cm():
    sc = {"w123": Score("w123", Label.FREEZING, Confidence.LOW, "why", 7.6180339, None)}
    e = build_status([lake], sc, frozenset(), frozenset(), {}, RUN, None)["lakes"]["w123"]
    assert e["thickness_cm"] == 8 and isinstance(e["thickness_cm"], int)
