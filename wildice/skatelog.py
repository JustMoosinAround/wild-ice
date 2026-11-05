"""Find past skating trips in exported activity tracks and look up the satellite view.

Run on your own computer (your tracks and Copernicus login stay there):

    python -m wildice.skatelog ~/Dropbox/GPX

Reads every Oct-Apr activity file (.gpx / .fit, optionally .gz) named like
`2025-02-08_IceSkate_i123.fit.gz`, keeps tracks that spend enough time on a catalog
lake, then asks Copernicus for Sentinel-2 and Landsat numbers on that lake for a week
either side.

Writes, next to the repo (both gitignored, never commit them):
  skate_reference.local.md  table of trips, clear-sky looks and Copernicus Browser links
  backtest.local.yaml       each IceSkate trip added once as `observed: skated`

A watch can save a skate as a hike or run that was retyped on Strava later, and the
export keeps the watch's type. List those file ids (the `i123` part) under `ice_skate:`
in skate_overrides.local.yaml (gitignored) and they are treated as IceSkate.
"""
from __future__ import annotations

import gzip
import io
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import shapely
import yaml
from shapely.geometry import shape

from wildice.catalog import load_catalog
from wildice.config import Config, load_config
from wildice.geo import _project, _TO_AK
from wildice.models import Lake, SourceUnavailable, SurfaceClass
from wildice.publish import browser_url
from wildice.score import classify_ls, classify_s2

LOCAL_TZ = ZoneInfo("America/Anchorage")
WINTER_MONTHS = {10, 11, 12, 1, 2, 3, 4}
SHORE_SLACK_M = 60       # catalog outlines are shrunk from the shore; let tracks touch it
MIN_MINUTES = 10         # time on one lake for a trip to count
MIN_SHARE = 0.3          # ...and this share of the moving time (walk in, skate, walk out)
MAX_GAP_S = 300          # longer gaps between points (pauses, lost signal) are not counted
WINDOW_DAYS = 7          # satellite looks this many days either side of the trip
SKATE_ACTIVITIES = {"IceSkate"}  # file-name types logged to the backtest as skated
_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_([A-Za-z]+)_")
_ID = re.compile(r"^\d{4}-\d{2}-\d{2}_[A-Za-z]+_([^._]+)\.")
_SEMI = 180.0 / 2 ** 31  # FIT semicircles to degrees

Point = tuple[float, float, datetime]  # lat, lon, UTC time


@dataclass(frozen=True)
class Trip:
    day: date            # local Alaska date
    lake: Lake
    activity: str        # type from the file name, e.g. IceSkate, Walk
    minutes: float       # time on the lake
    share: float         # share of the track's time spent on the lake
    file: str


@dataclass(frozen=True)
class Look:
    day: date
    cls: SurfaceClass
    brightness: float
    ndsi: float
    sensor: str = "s2"           # "s2" Sentinel-2 or "ls" Landsat 8-9
    temp_c: float | None = None  # Landsat surface temperature


def parse_name(name: str) -> tuple[date, str] | None:
    m = _NAME.match(name)
    if not m:
        return None
    try:
        return date.fromisoformat(m[1]), m[2]
    except ValueError:
        return None


def file_id(name: str) -> str | None:
    """The activity id in a file name, e.g. `i123` in `2025-02-08_Hike_i123.fit.gz`."""
    m = _ID.match(name)
    return m[1] if m else None


def load_skate_ids(path: Path) -> set[str]:
    """File ids listed under `ice_skate:` in the overrides file; empty if it is missing."""
    path = Path(path)
    if not path.exists():
        return set()
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(i) for i in doc.get("ice_skate") or []}


def _open_bytes(path: Path) -> bytes:
    data = Path(path).read_bytes()
    return gzip.decompress(data) if path.name.endswith(".gz") else data


def _gpx_points(data: bytes) -> list[Point]:
    out: list[Point] = []
    for el in ET.fromstring(data).iter():
        if not el.tag.endswith("trkpt"):
            continue
        t = next((c.text for c in el if c.tag.endswith("time")), None)
        if t is None:
            continue
        when = datetime.fromisoformat(t.strip().replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        out.append((float(el.get("lat")), float(el.get("lon")), when.astimezone(timezone.utc)))
    return out


def _fit_points(data: bytes) -> list[Point]:
    try:
        import fitdecode
    except ImportError as exc:
        raise RuntimeError("reading .fit files needs: pip install fitdecode") from exc
    out: list[Point] = []
    with fitdecode.FitReader(io.BytesIO(data)) as fit:
        for frame in fit:
            if not (isinstance(frame, fitdecode.FitDataMessage) and frame.name == "record"):
                continue
            vals = {f.name: f.value for f in frame.fields}
            lat, lon, ts = vals.get("position_lat"), vals.get("position_long"), vals.get("timestamp")
            if lat is None or lon is None or ts is None:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out.append((lat * _SEMI, lon * _SEMI, ts.astimezone(timezone.utc)))
    return out


def read_track(path: Path) -> list[Point]:
    path = Path(path)
    base = path.name[:-3] if path.name.endswith(".gz") else path.name
    data = _open_bytes(path)
    if base.endswith(".gpx"):
        return _gpx_points(data)
    if base.endswith(".fit"):
        return _fit_points(data)
    raise ValueError(f"unsupported file type: {path.name}")


def _lake_shapes(lakes: list[Lake]) -> list[tuple[Lake, object]]:
    out = []
    for lake in lakes:
        if lake.interior is None:
            continue
        out.append((lake, _project(shape(lake.interior)).buffer(SHORE_SLACK_M)))
    return out


def match_lake(points: list[Point], lakes, min_minutes: float = MIN_MINUTES
               ) -> tuple[Lake, float, float] | None:
    """The lake the track spends the most time on, with minutes and share, if enough."""
    if len(points) < 2:
        return None
    shapes = lakes if lakes and isinstance(lakes[0], tuple) else _lake_shapes(lakes)
    lats = np.array([p[0] for p in points])
    lons = np.array([p[1] for p in points])
    x, y = _TO_AK.transform(lons, lats)
    gaps = np.array([(b[2] - a[2]).total_seconds() for a, b in zip(points, points[1:])])
    gaps = np.where((gaps > 0) & (gaps <= MAX_GAP_S), gaps, 0.0)
    total = gaps.sum()
    if total <= 0:
        return None
    xmin, xmax, ymin, ymax = x.min(), x.max(), y.min(), y.max()
    best = None
    for lake, geom in shapes:
        bx0, by0, bx1, by1 = geom.bounds
        if bx0 > xmax or bx1 < xmin or by0 > ymax or by1 < ymin:
            continue
        inside = shapely.contains_xy(geom, x, y)
        both = inside[:-1] & inside[1:]
        secs = gaps[both].sum()
        if secs > 0 and (best is None or secs > best[1]):
            best = (lake, secs)
    if best is None:
        return None
    minutes, share = best[1] / 60.0, best[1] / total
    if minutes < min_minutes or share < MIN_SHARE:
        return None
    return best[0], round(minutes, 1), round(share, 3)


def _local_day(points: list[Point], lake: Lake, shapes) -> date:
    geom = next(g for lk, g in shapes if lk.id == lake.id)
    for lat, lon, t in points:
        x, y = _TO_AK.transform(lon, lat)
        if shapely.contains_xy(geom, x, y):
            return t.astimezone(LOCAL_TZ).date()
    return points[0][2].astimezone(LOCAL_TZ).date()


def find_trips(folder: Path, lakes: list[Lake], skate_ids: set[str] = frozenset()
               ) -> tuple[list[Trip], list[str]]:
    """Winter tracks that spent enough time on a catalog lake, and files that failed.

    Files whose id is in `skate_ids` count as IceSkate whatever their name says."""
    shapes = _lake_shapes(lakes)
    trips: list[Trip] = []
    skipped: list[str] = []
    for path in sorted(Path(folder).iterdir()):
        parsed = parse_name(path.name)
        if parsed is None or parsed[0].month not in WINTER_MONTHS:
            continue
        if not re.search(r"\.(gpx|fit)(\.gz)?$", path.name):
            continue
        try:
            points = read_track(path)
        except Exception as exc:  # one bad file must not stop the scan
            skipped.append(f"{path.name}: {exc}")
            continue
        m = match_lake(points, shapes)
        if m is None:
            continue
        lake, minutes, share = m
        activity = "IceSkate" if file_id(path.name) in skate_ids else parsed[1]
        trips.append(Trip(_local_day(points, lake, shapes), lake, activity, minutes, share,
                          path.name))
    return trips, skipped


def nearby_looks(client, trip: Trip, cfg: Config) -> list[Look]:
    """Clear Sentinel-2 and Landsat looks at the lake within WINDOW_DAYS of the trip,
    oldest first."""
    start = trip.day - timedelta(days=WINDOW_DAYS)
    end = trip.day + timedelta(days=WINDOW_DAYS)
    looks = []
    for obs in client.s2_stats(trip.lake.interior, start, end):
        cls = classify_s2(obs, cfg)
        if cls is None:
            continue
        denom = obs.b03 + obs.b11
        looks.append(Look(obs.day, cls, round((obs.b03 + obs.b04) / 2, 3),
                          round((obs.b03 - obs.b11) / denom, 3) if denom else 0.0))
    for lobs in client.ls_stats(trip.lake.interior, start, end):
        cls = classify_ls(lobs, cfg)
        if cls is None:
            continue
        denom = lobs.b03 + lobs.b06
        looks.append(Look(lobs.day, cls, round((lobs.b03 + lobs.b04) / 2, 3),
                          round((lobs.b03 - lobs.b06) / denom, 3) if denom else 0.0,
                          "ls", lobs.temp_c))
    return sorted(looks, key=lambda lk: (lk.day, lk.sensor))


def merge_backtest(path: Path, trips: list[Trip]) -> tuple[int, int]:
    """Add each skating (lake, day) once as skated; returns (added, removed).

    Other trips on a lake (walks, skis) say nothing about skateable ice. Older
    versions logged them as skated, so those rows are removed again."""
    path = Path(path)
    doc = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None) or {}
    obs = list(doc.get("observations") or [])
    skates = [t for t in trips if t.activity in SKATE_ACTIVITIES]
    skate_keys = {(t.lake.id, t.day.isoformat()) for t in skates}
    other_keys = {(t.lake.id, t.day.isoformat()) for t in trips} - skate_keys
    kept = [o for o in obs
            if not (o.get("observed") == "skated"
                    and (str(o.get("lake_id")), str(o.get("day"))) in other_keys)]
    removed = len(obs) - len(kept)
    obs = kept
    have = {(str(o.get("lake_id")), str(o.get("day"))) for o in obs}
    added = 0
    for t in skates:
        key = (t.lake.id, t.day.isoformat())
        if key in have:
            continue
        have.add(key)
        obs.append({"lake_id": t.lake.id, "day": t.day.isoformat(), "observed": "skated"})
        added += 1
    doc["observations"] = obs
    path.write_text("# Personal skating log. Gitignored: never commit.\n"
                    + yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return added, removed


def reference_markdown(rows: list[tuple[Trip, list[Look] | None, str | None]]) -> str:
    lines = [
        "# Skating reference (private, do not commit)",
        "",
        f"Clear Sentinel-2 and Landsat looks within {WINDOW_DAYS} days of each trip. "
        "Brightness is the mean visible reflectance (dark ice is low); "
        "NDSI is high for snow. Landsat looks add the surface temperature.",
        "",
        "| Day | Lake | Activity | Min on lake | Clear looks |",
        "|---|---|---|---|---|",
    ]
    for trip, looks, err in rows:
        name = trip.lake.name or trip.lake.id
        if err:
            cell = f"error: {err}"
        elif not looks:
            cell = "none (cloudy or no imagery)"
        else:
            cell = "<br>".join(
                f"[{lk.day.isoformat()}]"
                f"({browser_url(trip.lake.lat, trip.lake.lon, lk.day, lk.sensor)}) "
                + ("Landsat " if lk.sensor == "ls" else "")
                + f"{lk.cls.value} (brightness {lk.brightness:.3f}, NDSI {lk.ndsi:.2f}"
                + (f", {lk.temp_c:+.0f} °C" if lk.temp_c is not None else "") + ")"
                for lk in looks)
        lines.append(f"| {trip.day.isoformat()} | {name} ({trip.lake.id}) | {trip.activity} "
                     f"| {trip.minutes:.0f} | {cell} |")
    looks_all = [lk for _, ls, _ in rows for lk in (ls or [])]
    if looks_all:
        lines += ["", "## Counts", ""]
        for cls in SurfaceClass:
            n = sum(lk.cls is cls for lk in looks_all)
            lines.append(f"- {cls.value}: {n}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python -m wildice.skatelog <folder of activity files>")
        return 2
    root = Path.cwd()
    cfg = load_config(root / "config.yaml")
    lakes = load_catalog(root / "site" / "data" / "lakes.geojson")
    skate_ids = load_skate_ids(root / "skate_overrides.local.yaml")
    trips, skipped = find_trips(Path(args[0]).expanduser(), lakes, skate_ids)
    print(f"found {len(trips)} trips on catalog lakes "
          f"({sum(t.activity in SKATE_ACTIVITIES for t in trips)} skating)")
    for s in skipped:
        print(f"  skipped {s}")

    client = None
    cid, secret = os.environ.get("CDSE_CLIENT_ID"), os.environ.get("CDSE_CLIENT_SECRET")
    if cid and secret:
        from wildice.imagery import CopernicusClient
        from wildice.weather import make_session
        client = CopernicusClient(cid, secret, make_session())
    else:
        print("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET not set: listing trips without imagery")

    rows = []
    seen: dict[tuple[str, date], tuple[list[Look] | None, str | None]] = {}
    for trip in sorted(trips, key=lambda t: (t.day, t.lake.id)):
        key = (trip.lake.id, trip.day)
        if key not in seen:
            if client is None:
                seen[key] = (None, "no Copernicus login")
            else:
                try:
                    seen[key] = (nearby_looks(client, trip, cfg), None)
                except SourceUnavailable as exc:
                    seen[key] = (None, str(exc))
            print(f"  {trip.day} {trip.lake.name or trip.lake.id}: "
                  + (seen[key][1] or f"{len(seen[key][0])} clear looks"))
        rows.append((trip, *seen[key]))

    out = root / "skate_reference.local.md"
    out.write_text(reference_markdown(rows), encoding="utf-8")
    added, removed = merge_backtest(root / "backtest.local.yaml", trips)
    print(f"wrote {out.name}; backtest.local.yaml: added {added} skated days, "
          f"removed {removed} logged from non-skating trips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
