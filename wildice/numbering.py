"""Names for unnamed lakes: nearest town or landmark plus a number, e.g. "Willow 12".

There's no official numbering people use (the "Lake 217" names on old USGS maps are
surface elevations). Within each place, lakes are numbered nearest-first when first
seen; numbers are saved in state/lake_numbers.json and never change, so a lake added
later gets the next free number.
"""
from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from wildice.models import Lake

# (name, lat, lon): towns and well-known landmarks across the catalog region.
PLACES: list[tuple[str, float, float]] = [
    ("Anchorage", 61.2181, -149.9003), ("Eagle River", 61.3214, -149.5679), ("Chugiak", 61.3986, -149.4793),
    ("Girdwood", 60.9425, -149.1664), ("Portage", 60.8344, -148.9897), ("Whittier", 60.7733, -148.6839),
    ("Hope", 60.9203, -149.6406), ("Palmer", 61.5997, -149.1128), ("Wasilla", 61.5814, -149.4394),
    ("Big Lake", 61.5214, -149.9564), ("Knik", 61.4600, -149.7300), ("Point MacKenzie", 61.3650, -150.1050),
    ("Houston", 61.6303, -149.8181), ("Willow", 61.7472, -150.0372), ("Nancy Lake", 61.6900, -150.0100),
    ("Kashwitna", 61.8350, -150.0900), ("Caswell", 61.9550, -150.0550), ("Sunshine", 62.1450, -150.0950),
    ("Talkeetna", 62.3209, -150.1066), ("Trapper Creek", 62.3167, -150.2319), ("Petersville", 62.4900, -150.7700),
    ("Chulitna", 62.5600, -150.2400), ("Byers Lake", 62.7400, -150.1200), ("Skwentna", 61.9650, -151.1800),
    ("Yentna", 61.7300, -150.7000), ("Susitna", 61.5440, -150.5140), ("Tyonek", 61.0681, -151.1369),
    ("Beluga", 61.1700, -151.0400), ("Sutton", 61.7114, -148.8944), ("Chickaloon", 61.7975, -148.4625),
    ("Hatcher Pass", 61.7800, -149.2700), ("Sheep Mountain", 61.8100, -147.5100), ("Eureka", 61.9400, -147.1700),
    ("Lake Louise", 62.2900, -146.5600), ("Glennallen", 62.1092, -145.5464), ("Tazlina", 62.0650, -146.4500),
    ("Copper Center", 61.9550, -145.3050), ("Kenny Lake", 61.7350, -144.9450), ("Chitina", 61.5158, -144.4369),
    ("Valdez", 61.1308, -146.3483), ("Thompson Pass", 61.1300, -145.7400), ("Cordova", 60.5428, -145.7575),
    ("Moose Pass", 60.4878, -149.3689), ("Cooper Landing", 60.4908, -149.8333), ("Seward", 60.1042, -149.4422),
    ("Sterling", 60.5375, -150.7647), ("Soldotna", 60.4878, -151.0583), ("Kenai", 60.5544, -151.2583),
    ("Nikiski", 60.6903, -151.2889), ("Swan Lake", 60.7800, -150.5100), ("Kasilof", 60.3375, -151.2744),
    ("Clam Gulch", 60.2283, -151.3956), ("Ninilchik", 60.0464, -151.6689), ("Anchor Point", 59.7767, -151.8314),
    ("Homer", 59.6425, -151.5483), ("Tustumena", 60.2000, -150.9000), ("Skilak", 60.4300, -150.3500),
]

NUMBERS_FILE = "lake_numbers.json"


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _nearest(lake: Lake) -> tuple[str, float]:
    best = min(PLACES, key=lambda p: _km(lake.lat, lake.lon, p[1], p[2]))
    return best[0], _km(lake.lat, lake.lon, best[1], best[2])


def assign_numbers(lakes: Iterable[Lake], existing: dict[str, str]) -> dict[str, str]:
    """{lake id: "Place N"} for every unnamed lake: saved names kept, new ones numbered
    nearest-first after the highest number already used in their place."""
    out = dict(existing)
    used: dict[str, int] = {}
    for name in out.values():
        place, _, n = name.rpartition(" ")
        if n.isdigit():
            used[place] = max(used.get(place, 0), int(n))
    new: dict[str, list[tuple[float, str]]] = {}
    for lake in lakes:
        if lake.name or lake.id in out:
            continue
        place, km = _nearest(lake)
        new.setdefault(place, []).append((km, lake.id))
    for place, items in new.items():
        for km, lake_id in sorted(items):
            used[place] = used.get(place, 0) + 1
            out[lake_id] = f"{place} {used[place]}"
    return out


def apply_numbers(lakes: list[Lake], path: Path) -> list[Lake]:
    """Lakes with unnamed ones named from (and new numbers saved to) `path`."""
    path = Path(path)
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing = existing if isinstance(existing, dict) else {}
    except (OSError, ValueError):
        existing = {}
    numbers = assign_numbers(lakes, existing)
    if numbers != existing:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(numbers, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    return [replace(l, name=numbers[l.id]) if not l.name and l.id in numbers else l for l in lakes]
