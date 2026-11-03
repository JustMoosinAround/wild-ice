import gzip
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from wildice import skatelog
from wildice.config import load_config
from wildice.models import Lake, S2Obs, SurfaceClass

REPO = Path(__file__).resolve().parent.parent
CFG = load_config(REPO / "config.yaml")

# ~1.1 km x 0.5 km box near Anchorage
POLY = {"type": "Polygon", "coordinates": [[[-149.51, 60.99], [-149.49, 60.99],
                                             [-149.49, 61.00], [-149.51, 61.00],
                                             [-149.51, 60.99]]]}
LAKE = Lake("w1", "Test Lake", 200.0, 0.1, None, 60.995, -149.50, POLY, None)
T0 = datetime(2025, 2, 8, 20, 0, tzinfo=timezone.utc)


def _gpx(points):
    pts = "".join(f'<trkpt lat="{la}" lon="{lo}"><time>{t.strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>'
                  for la, lo, t in points)
    return ('<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><trkseg>{pts}</trkseg></trk></gpx>")


def _loop_on_lake(minutes=30, start=T0):
    # back and forth across the lake, one point a minute
    return [(60.995, -149.505 + 0.01 * (i % 2), start + timedelta(minutes=i))
            for i in range(minutes)]


def _write(tmp, name, text, gz=False):
    p = tmp / name
    if gz:
        p.write_bytes(gzip.compress(text.encode()))
    else:
        p.write_text(text)
    return p


def test_parse_name():
    assert skatelog.parse_name("2025-02-08_IceSkate_i194836691.fit.gz") == (date(2025, 2, 8), "IceSkate")
    assert skatelog.parse_name("notes.txt") is None


def test_read_gpx_plain_and_gz(tmp_path):
    pts = _loop_on_lake(3)
    a = skatelog.read_track(_write(tmp_path, "a.gpx", _gpx(pts)))
    b = skatelog.read_track(_write(tmp_path, "b.gpx.gz", _gpx(pts), gz=True))
    assert a == b
    assert len(a) == 3 and a[0][0] == 60.995 and a[0][2] == T0


def test_match_lake_on_lake_track():
    m = skatelog.match_lake(_loop_on_lake(30), [LAKE])
    assert m is not None
    lake, minutes, share = m
    assert lake.id == "w1" and minutes >= 25 and share > 0.9


def test_match_lake_ignores_track_off_lake():
    pts = [(61.2, -149.9 + 0.001 * i, T0 + timedelta(minutes=i)) for i in range(30)]
    assert skatelog.match_lake(pts, [LAKE]) is None


def test_match_lake_needs_enough_time_on_ice():
    # 4 minutes on the lake inside an hour-long walk elsewhere
    pts = [(61.2, -149.9 + 0.001 * i, T0 + timedelta(minutes=i)) for i in range(56)]
    pts += _loop_on_lake(4, start=T0 + timedelta(minutes=56))
    assert skatelog.match_lake(pts, [LAKE]) is None


def test_find_trips_skips_summer_and_unknown_files(tmp_path):
    _write(tmp_path, "2025-02-08_Walk_i1.gpx", _gpx(_loop_on_lake(30)))
    _write(tmp_path, "2025-07-08_Walk_i2.gpx", _gpx(_loop_on_lake(30)))
    _write(tmp_path, "readme.txt", "hi")
    trips, skipped = skatelog.find_trips(tmp_path, [LAKE])
    assert [(t.day, t.lake.id, t.activity) for t in trips] == [(date(2025, 2, 8), "w1", "Walk")]
    assert skipped == []


def test_find_trips_reports_unreadable_files(tmp_path):
    _write(tmp_path, "2025-02-08_IceSkate_i1.gpx", "<not xml")
    trips, skipped = skatelog.find_trips(tmp_path, [LAKE])
    assert trips == [] and skipped and "2025-02-08_IceSkate_i1.gpx" in skipped[0]


def test_find_trips_uses_local_alaska_date(tmp_path):
    # 2025-02-09 05:00 UTC is still Feb 8 in Anchorage
    late = datetime(2025, 2, 9, 5, 0, tzinfo=timezone.utc)
    _write(tmp_path, "2025-02-09_IceSkate_i1.gpx", _gpx(_loop_on_lake(30, start=late)))
    trips, _ = skatelog.find_trips(tmp_path, [LAKE])
    assert trips[0].day == date(2025, 2, 8)


class FakeClient:
    def __init__(self, s2):
        self.s2 = s2
        self.calls = []

    def s2_stats(self, geometry, start, end):
        self.calls.append((start, end))
        return [o for o in self.s2 if start <= o.day <= end]


def test_nearby_looks_classifies_clear_days():
    day = date(2025, 2, 8)
    client = FakeClient([
        S2Obs(day - timedelta(days=2), 0.95, 0.05, 0.04, 0.03),   # dark
        S2Obs(day + timedelta(days=1), 0.95, 0.80, 0.78, 0.10),   # white
        S2Obs(day + timedelta(days=3), 0.10, 0.80, 0.78, 0.10),   # too cloudy
    ])
    trip = skatelog.Trip(day, LAKE, "IceSkate", 30.0, 1.0, "f")
    looks = skatelog.nearby_looks(client, trip, CFG)
    assert [(lk.day, lk.cls) for lk in looks] == [
        (day - timedelta(days=2), SurfaceClass.DARK),
        (day + timedelta(days=1), SurfaceClass.WHITE),
    ]
    assert client.calls == [(day - timedelta(days=skatelog.WINDOW_DAYS),
                             day + timedelta(days=skatelog.WINDOW_DAYS))]


def test_merge_backtest_adds_once_and_keeps_existing(tmp_path):
    p = tmp_path / "backtest.local.yaml"
    p.write_text(yaml.safe_dump({"observations": [
        {"lake_id": "w9", "day": "2024-12-01", "observed": "snow"}]}))
    trip = skatelog.Trip(date(2025, 2, 8), LAKE, "IceSkate", 30.0, 1.0, "f")
    assert skatelog.merge_backtest(p, [trip, trip]) == 1
    assert skatelog.merge_backtest(p, [trip]) == 0
    obs = yaml.safe_load(p.read_text())["observations"]
    assert {"lake_id": "w9", "day": "2024-12-01", "observed": "snow"} in obs
    assert {"lake_id": "w1", "day": "2025-02-08", "observed": "skated"} in obs
    assert len(obs) == 2


def test_reference_table_has_links_and_classes():
    day = date(2025, 2, 8)
    trip = skatelog.Trip(day, LAKE, "IceSkate", 30.0, 1.0, "f")
    looks = [skatelog.Look(day - timedelta(days=2), SurfaceClass.DARK, 0.045, 0.25)]
    text = skatelog.reference_markdown([(trip, looks, None)])
    assert "Test Lake" in text and "2025-02-08" in text and "dark" in text
    assert "browser.dataspace.copernicus.eu" in text and "2025-02-06" in text
