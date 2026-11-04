import json
from datetime import date, timedelta
from pathlib import Path

from wildice.config import load_config
from wildice.icemodel import run_ice_model
from wildice.models import Confidence, DayWeather, IceState, Label, Score, SurfaceClass
from wildice.reports import Report, apply_report, ice_with_report, load_reports

REPO = Path(__file__).resolve().parent.parent
CFG = load_config(REPO / "config.yaml")
RUN = date(2026, 11, 4)


def _write(d: Path, name: str, obj) -> None:
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(obj) if not isinstance(obj, str) else obj)


def test_load_reports_keeps_latest_per_lake(tmp_path):
    r = tmp_path / "ratings"
    _write(r, "2026-11-02-100-w1.json", {"lake_id": "w1", "day": "2026-11-02", "rating": "skated", "note": ""})
    _write(r, "2026-11-04-300-w1.json", {"lake_id": "w1", "day": "2026-11-04", "rating": "water", "note": "wide open"})
    _write(r, "2026-11-03-200-w2.json", {"lake_id": "w2", "day": "2026-11-03", "rating": "snow", "note": ""})
    _write(r, "2026-11-03-250-w3.json", "{broken")
    _write(r, "2026-11-03-260-w4.json", {"lake_id": "w4", "day": "2026-11-03", "rating": "lava"})
    _write(r, "2026-11-09-999-w5.json", {"lake_id": "w5", "day": "2026-11-09", "rating": "snow"})  # future
    got = load_reports(r, RUN, season_start=date(2026, 10, 1))
    assert got == {"w1": Report(date(2026, 11, 4), "water", "wide open"),
                   "w2": Report(date(2026, 11, 3), "snow", "")}


def test_load_reports_ignores_last_season(tmp_path):
    r = tmp_path / "ratings"
    _write(r, "2026-03-02-100-w1.json", {"lake_id": "w1", "day": "2026-03-02", "rating": "skated"})
    assert load_reports(r, RUN, season_start=date(2026, 10, 1)) == {}
    assert load_reports(tmp_path / "missing", RUN, season_start=date(2026, 10, 1)) == {}


def _cold(start: date, end: date, t=-12.0):
    out, d = [], start
    while d <= end:
        out.append(DayWeather(d, t - 3, t + 3, t, 0.0, 0.0, 10.0))
        d += timedelta(days=1)
    return out


def test_open_water_report_restarts_ice():
    wx = _cold(date(2026, 10, 1), RUN)
    before = run_ice_model(wx, CFG)
    assert before.thickness_cm > 20
    trace = []
    ice = ice_with_report(wx, CFG, None, None, Report(RUN, "water", ""), trace)
    assert ice.thickness_cm == 0.0
    assert trace[-1] == (RUN, 0.0, 0.0) and len(trace) == len(wx)
    # two cold days later a little ice is back, but not skateable
    wx2 = _cold(date(2026, 10, 1), RUN + timedelta(days=2))
    ice2 = ice_with_report(wx2, CFG, None, None, Report(RUN, "water", ""))
    assert 0 < ice2.thickness_cm < CFG.ice.skate_cm


def test_other_reports_leave_ice_alone():
    wx = _cold(date(2026, 10, 1), RUN)
    assert ice_with_report(wx, CFG, None, None, Report(RUN, "snow", "")) == run_ice_model(wx, CFG)
    assert ice_with_report(wx, CFG, None, None, None) == run_ice_model(wx, CFG)


def _score(label=Label.LIKELY_BLACK_ICE, conf=Confidence.MEDIUM):
    return Score("w1", label, conf, "~27 cm est.", 27.0, None)


def _ice(last_snow=None, snow=0.0):
    return IceState(500, 27, date(2026, 10, 20), None, snow, last_snow, ())


def test_water_report_note_and_confidence():
    sc = apply_report(_score(Label.OPEN_WATER, Confidence.LOW), Report(RUN, "water", "wide open"),
                      _ice(), {}, RUN, CFG)
    assert sc.label is Label.OPEN_WATER and sc.confidence is Confidence.HIGH
    assert sc.reason.startswith('You reported open water on Nov 4 ("wide open"); ')


def test_skated_report_holds_until_snow():
    rep = Report(RUN - timedelta(days=2), "skated", "")
    sc = apply_report(_score(Label.UNKNOWN), rep, _ice(), {}, RUN, CFG)
    assert sc.label is Label.LIKELY_BLACK_ICE and sc.confidence is Confidence.HIGH
    snowed = _ice(last_snow=RUN - timedelta(days=1), snow=5.0)
    sc = apply_report(_score(Label.SNOW_COVERED), rep, snowed, {}, RUN, CFG)
    assert sc.label is Label.SNOW_COVERED


def test_snow_report_holds_until_dark_image():
    rep = Report(RUN - timedelta(days=3), "snow", "")
    sc = apply_report(_score(), rep, _ice(), {}, RUN, CFG)
    assert sc.label is Label.SNOW_COVERED
    cleared = {RUN - timedelta(days=1): SurfaceClass.DARK}
    sc = apply_report(_score(), rep, _ice(), cleared, RUN, CFG)
    assert sc.label is Label.LIKELY_BLACK_ICE


def test_reports_expire_after_a_week():
    rep = Report(RUN - timedelta(days=8), "snow", "")
    sc = apply_report(_score(), rep, _ice(), {}, RUN, CFG)
    assert sc == _score()


def test_rough_report_keeps_label_and_adds_note():
    sc = apply_report(_score(), Report(RUN, "rough", ""), _ice(), {}, RUN, CFG)
    assert sc.label is Label.LIKELY_BLACK_ICE
    assert sc.reason.startswith("You reported rough ice on Nov 4; ")
