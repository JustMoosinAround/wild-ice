from datetime import date, datetime, timezone

from shapely.geometry import box, mapping

from wildice.models import Lake
from wildice.scenes import Scene, load_seen, new_sensors, save_seen

UTC = timezone.utc
T1 = datetime(2025, 11, 10, 21, 5, tzinfo=UTC)
T2 = datetime(2025, 11, 12, 21, 5, tzinfo=UTC)


def lake(lake_id, west, south, size=0.01):
    geom = mapping(box(west, south, west + size, south + size))
    return Lake(lake_id, None, 100.0, 1.0, None, south, west, geom, None)


A = lake("wA", -149.5, 61.0)   # inside both footprints
B = lake("wB", -147.0, 62.0)   # inside the S2 footprint only
C = Lake("wC", None, 100.0, 1.0, None, 61.0, -149.5, None, "narrow")  # no geometry
S2_FOOT = box(-150.0, 60.5, -146.5, 62.5)
S1_FOOT = box(-150.0, 60.5, -148.5, 61.5)


def test_new_scene_marks_covered_lakes_by_sensor():
    scenes = [Scene("s2", T1, S2_FOOT), Scene("s2", T2, S2_FOOT), Scene("s1", T1, S1_FOOT)]
    got = new_sensors([A, B, C], scenes, seen={})
    assert got == {"wA": {"s2": T2, "s1": T1}, "wB": {"s2": T2}}


def test_already_seen_scene_is_not_new():
    scenes = [Scene("s2", T1, S2_FOOT), Scene("s1", T1, S1_FOOT)]
    seen = {"wA": {"s2": T1}, "wB": {"s2": T2}}
    assert new_sensors([A, B], scenes, seen) == {"wA": {"s1": T1}}


def test_newer_scene_than_seen_is_new():
    scenes = [Scene("s2", T2, S2_FOOT)]
    assert new_sensors([A], scenes, {"wA": {"s2": T1}}) == {"wA": {"s2": T2}}


def test_no_scenes_nothing_new():
    assert new_sensors([A, B], [], {}) == {}


def test_seen_roundtrip_drops_old_season_and_junk(tmp_path):
    p = tmp_path / "seen.json"
    save_seen(p, {"wA": {"s2": T2}, "wOld": {"s1": datetime(2024, 12, 1, tzinfo=UTC)}})
    raw = p.read_text(encoding="utf-8")
    p.write_text(raw.replace("{", '{"bad": {"s2": "not a time"}, ', 1), encoding="utf-8")
    assert load_seen(p, date(2025, 10, 1)) == {"wA": {"s2": T2}}


def test_missing_seen_file_is_empty(tmp_path):
    assert load_seen(tmp_path / "none.json", date(2025, 10, 1)) == {}
