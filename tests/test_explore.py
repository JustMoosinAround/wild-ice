from datetime import date

from wildice.explore import came_in, timeline
from wildice.models import ResetEvent, ResetKind, SurfaceClass
from wildice.reports import Report

RUN = date(2026, 11, 22)


def _h(*labels):
    """history rows for the days before RUN, oldest first"""
    n = len(labels)
    return [{"day": date(2026, 11, 22 - n + i).isoformat(), "label": lab} for i, lab in enumerate(labels)]


def test_came_in_is_first_day_of_current_in_run():
    hist = _h("snow_covered", "snow_covered", "likely_black_ice", "likely_black_ice")
    assert came_in(hist, "likely_black_ice", RUN) == date(2026, 11, 20)


def test_came_in_survives_a_one_day_dip():
    hist = _h("snow_covered", "likely_black_ice", "unknown", "likely_black_ice")
    assert came_in(hist, "likely_black_ice", RUN) == date(2026, 11, 19)
    # two days out ends the run
    hist = _h("likely_black_ice", "unknown", "unknown", "likely_black_ice")
    assert came_in(hist, "likely_black_ice", RUN) == date(2026, 11, 21)


def test_came_in_today_and_none_when_not_in():
    assert came_in(_h("snow_covered"), "rough_ice", RUN) == RUN
    assert came_in(_h("likely_black_ice"), "snow_covered", RUN) is None
    assert came_in([], "likely_black_ice", RUN) == RUN


def test_timeline_newest_first_and_capped():
    rep = Report(date(2026, 11, 21), "skated", "", grade="B+")
    classes = {date(2026, 11, 20): SurfaceClass.CRACKED, date(2026, 11, 12): SurfaceClass.WHITE}
    t = timeline(rep, classes, (date(2026, 11, 18), 8.0, "Willow"),
                 ResetEvent(date(2026, 11, 20), ResetKind.CONFIRMED))
    assert [e["text"] for e in t] == ["Skated (B+)", "Crack network seen", "8 cm new snow at Willow",
                                      "White (snow) on image"]
    assert [e["day"] for e in t] == ["2026-11-21", "2026-11-20", "2026-11-18", "2026-11-12"]
    assert len(timeline(rep, classes, (date(2026, 11, 18), 8.0, "Willow"), None, limit=2)) == 2


def test_timeline_has_no_names_or_notes():
    rep = Report(date(2026, 11, 21), "water", "secret spot", source="friend")
    t = timeline(rep, {}, None, None)
    assert t == [{"day": "2026-11-21", "kind": "report", "text": "Open water reported"}]
    assert "secret" not in str(t)
