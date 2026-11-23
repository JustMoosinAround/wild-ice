import json

from wildice.models import Lake
from wildice.numbering import PLACES, apply_numbers, assign_numbers


def _lake(i, lat, lon, name=None):
    return Lake(i, name, 20, 0.1, None, lat, lon, None, None)


WILLOW = next(p for p in PLACES if p[0] == "Willow")


def test_unnamed_lakes_get_nearest_place_and_numbers_by_distance():
    lakes = [_lake("w3", WILLOW[1] + 0.02, WILLOW[2]), _lake("w1", WILLOW[1] + 0.01, WILLOW[2]),
             _lake("w2", WILLOW[1], WILLOW[2], name="Long Lake")]
    got = assign_numbers(lakes, {})
    assert got == {"w1": "Willow 1", "w3": "Willow 2"}  # nearest first; named lakes skipped


def test_numbers_never_change_and_new_lakes_get_the_next_free_one():
    old = {"w1": "Willow 1", "w3": "Willow 2"}
    lakes = [_lake("w9", WILLOW[1] + 0.001, WILLOW[2]), _lake("w1", WILLOW[1] + 0.01, WILLOW[2]),
             _lake("w3", WILLOW[1] + 0.02, WILLOW[2])]
    assert assign_numbers(lakes, old) == {"w1": "Willow 1", "w3": "Willow 2", "w9": "Willow 3"}


def test_apply_numbers_names_unnamed_lakes_only(tmp_path):
    p = tmp_path / "lake_numbers.json"
    lakes = [_lake("w1", WILLOW[1] + 0.01, WILLOW[2]), _lake("w2", WILLOW[1], WILLOW[2], name="Long Lake")]
    out = apply_numbers(lakes, p)
    assert [l.name for l in out] == ["Willow 1", "Long Lake"]
    assert json.loads(p.read_text()) == {"w1": "Willow 1"}
    assert [l.name for l in apply_numbers(lakes, p)] == ["Willow 1", "Long Lake"]


def test_places_cover_the_region_with_unique_names():
    names = [p[0] for p in PLACES]
    assert len(names) == len(set(names)) and len(names) >= 40
    for _, lat, lon in PLACES:
        assert 59.3 <= lat <= 63.2 and -153 <= lon <= -143.5
