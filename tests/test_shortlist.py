from datetime import date
from pathlib import Path

from wildice.config import load_config
from wildice.models import IceState, Lake, ResetEvent, ResetKind
from wildice.publish import browser_url, display_name
from wildice.shortlist import shortlist

cfg = load_config(Path("config.yaml"))
GEOM = {"type": "Polygon", "coordinates": []}
SNOW_DAY = date(2025, 11, 5)


def mk(id, area=50, interior=GEOM, name="L"):
    return Lake(id, name, area, 1, None, 61, -149, interior, None)


def ice(h=5, snow=0.0, reset=None, last_snow=None, possible=()):
    return IceState(100, h, None, reset, snow, last_snow, tuple(possible))


def test_shortlist_skips_open_water_but_keeps_snowed_last():
    # Snowed-over lakes still get satellite checks (wind can clear them),
    # after the lakes the weather says are clear.
    lakes = [mk("a"), mk("b", 900), mk("c")]
    st = {"a": ice(h=1), "b": ice(snow=10, last_snow=SNOW_DAY), "c": ice()}
    assert shortlist(lakes, st, frozenset(), cfg, 100) == ["c", "b"]


def test_shortlist_keeps_snowed_with_possible_reset():
    lakes = [mk("a"), mk("b"), mk("c")]
    later = date(2025, 11, 8)
    st = {
        "a": ice(snow=10, last_snow=SNOW_DAY, possible=(ResetEvent(later, ResetKind.POSSIBLE),)),
        "b": ice(snow=10, last_snow=SNOW_DAY, reset=ResetEvent(later, ResetKind.CONFIRMED)),
        "c": ice(snow=10, last_snow=SNOW_DAY, possible=(ResetEvent(date(2025, 11, 1), ResetKind.POSSIBLE),)),
    }
    got = shortlist(lakes, st, frozenset(), cfg, 100)
    assert sorted(got[:2]) == ["a", "b"] and got[2] == "c"  # c is still snowed over


def test_shortlist_pinned_first_then_area():
    lakes = [mk("a", 10), mk("b", 500), mk("c", 100), mk("p", 5)]
    st = {i: ice() for i in "abc"}
    st["p"] = ice(h=0)
    assert shortlist(lakes, st, frozenset({"p"}), cfg, 100) == ["p", "b", "c", "a"]


def test_shortlist_truncates_to_budget():
    lakes = [mk(f"w{i}", 10 + i) for i in range(5)]
    st = {l.id: ice() for l in lakes}
    assert len(shortlist(lakes, st, frozenset(), cfg, 4)) == 2
    assert len(shortlist(lakes, st, frozenset(), cfg, 5)) == 2
    assert shortlist(lakes, st, frozenset(), cfg, 1) == []


def test_shortlist_excludes_no_geometry_even_if_pinned():
    lakes = [mk("a", interior=None), mk("b")]
    st = {"a": ice(), "b": ice()}
    assert shortlist(lakes, st, frozenset({"a"}), cfg, 100) == ["b"]


def test_display_name_unnamed():
    assert display_name(mk("w1", 34.2, name=None)) == "Unnamed lake (34 ac)"
    assert display_name(mk("w1", name="Lake X")) == "Lake X"


def test_browser_url_has_date():
    url = browser_url(61.0, -149.0, date(2025, 11, 11))
    assert "fromTime=2025-11-11T00:00:00.000Z" in url
    assert "toTime=2025-11-11T23:59:59.999Z" in url
    assert url.startswith("https://browser.dataspace.copernicus.eu/?zoom=14&lat=61")
    assert "fromTime" not in browser_url(61.0, -149.0, None)


def test_shortlist_excludes_hidden_even_if_pinned():
    lakes = [mk("a", 500), mk("b", 100), mk("p", 5)]
    st = {i: ice() for i in "abp"}
    got = shortlist(lakes, st, frozenset({"p"}), cfg, 100, hidden=frozenset({"a", "p"}))
    assert got == ["b"]


def test_snowed_lakes_rotate_oldest_checked_first():
    lakes = [mk("old", 10), mk("new", 900), mk("never", 50), mk("clear", 5)]
    snowed = ice(snow=10, last_snow=SNOW_DAY)
    st = {"old": snowed, "new": snowed, "never": snowed, "clear": ice()}
    checked = {"old": date(2025, 11, 2), "new": date(2025, 11, 9)}
    got = shortlist(lakes, st, frozenset(), cfg, 100, last_checked=checked)
    assert got == ["clear", "never", "old", "new"]


def test_allowance_drops_most_recently_checked_snowed_lakes():
    lakes = [mk("old"), mk("new"), mk("clear")]
    snowed = ice(snow=10, last_snow=SNOW_DAY)
    st = {"old": snowed, "new": snowed, "clear": ice()}
    checked = {"old": date(2025, 11, 2), "new": date(2025, 11, 9)}
    got = shortlist(lakes, st, frozenset(), cfg, 4, last_checked=checked)  # room for 2
    assert got == ["clear", "old"]


def test_pinned_snowed_lake_still_first():
    lakes = [mk("p", 5), mk("c", 900)]
    st = {"p": ice(snow=10, last_snow=SNOW_DAY), "c": ice()}
    assert shortlist(lakes, st, frozenset({"p"}), cfg, 100) == ["p", "c"]
