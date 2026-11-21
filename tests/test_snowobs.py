from datetime import date
from pathlib import Path

import pytest
import requests
import responses

from wildice.config import load_config
from wildice.models import DayWeather, Lake
from wildice import snowobs
from wildice.snowobs import Station, apply_measured, latest_measured, match_station, parse_cocorahs, parse_snotel

CFG = load_config(Path(__file__).resolve().parent.parent / "config.yaml")

SNOTEL = """#comment lines from NRCS
#more
Date,Station Name,Station Id,Latitude,Longitude,Elevation (ft),Snow Depth (in) Start of Day Values,Snow Water Equivalent (in) Start of Day Values
2026-11-19,Anchorage Hillside,1070,61.11,-149.67,2080,7,1.5
2026-11-20,Anchorage Hillside,1070,61.11,-149.67,2080,17,2.2
2026-11-21,Anchorage Hillside,1070,61.11,-149.67,2080,15,2.3
2026-11-19,Windy Ridge,9999,61.5,-149.0,3000,20,5.0
2026-11-20,Windy Ridge,9999,61.5,-149.0,3000,26,5.0
"""

COCORAHS = """ObservationDate,ObservationTime,EntryDateTime,StationNumber,StationName,Latitude,Longitude,TotalPrecipAmt,NewSnowDepth,NewSnowSWE,TotalSnowDepth,TotalSnowSWE,DateTimeStamp
2026-11-20, 07:00 AM, x, AK-AB-51, Anchorage 4.5 E, 61.213, -149.7649, 0.20, 6.6, NA, 7.0, NA, x
2026-11-19, 07:00 AM, x, AK-AB-51, Anchorage 4.5 E, 61.213, -149.7649, 0.01, T, NA, 3.0, NA, x
2026-11-18, 07:00 AM, x, AK-AB-51, Anchorage 4.5 E, 61.213, -149.7649, 0.00, NA, NA, NA, NA, x
2026-11-20, 06:00 AM, x, AK-JB-11, Juneau 5.6 NW, 58.35, -134.53, 0.06, 2.0, NA, NA, NA, x
"""


def test_snotel_new_snow_from_depth_rise_with_swe_rise():
    stations, obs = parse_snotel(SNOTEL)
    hill = next(s for s in stations if s.name == "Anchorage Hillside")
    assert hill.source == "SNOTEL" and hill.elev_m == pytest.approx(634, abs=1)
    # start-of-day Nov 20 minus Nov 19 = snow that fell on Nov 19
    assert obs[hill.id][date(2026, 11, 19)] == pytest.approx(10 * 2.54)
    assert obs[hill.id][date(2026, 11, 20)] == 0.0      # settling is not new snow
    windy = next(s for s in stations if s.name == "Windy Ridge")
    assert obs[windy.id][date(2026, 11, 19)] == 0.0     # depth up, SWE flat: drifting


def test_cocorahs_new_snow_belongs_to_the_day_before():
    stations, obs = parse_cocorahs(COCORAHS, CFG.region.bbox)
    assert [s.name for s in stations] == ["Anchorage 4.5 E"]   # Juneau is outside the region
    s = stations[0]
    assert s.source == "CoCoRaHS" and s.elev_m is None
    assert obs[s.id] == {date(2026, 11, 19): pytest.approx(6.6 * 2.54, abs=0.01), date(2026, 11, 18): 0.0}
    # an "NA" report (Nov 18 morning -> Nov 17) says nothing


def _lake(lat, lon, elev):
    return Lake("w1", "L", 50, 0.1, None, lat, lon, None, None, elev_m=elev)


def test_match_nearest_station_within_distance_and_elevation():
    near_low = Station("c1", "Town", 61.20, -149.80, None, "CoCoRaHS")
    hill = Station("s1", "Hillside", 61.11, -149.67, 634.0, "SNOTEL")
    far = Station("s2", "Far", 62.5, -147.0, 50.0, "SNOTEL")
    assert match_station(_lake(61.19, -149.78, 40.0), [hill, near_low, far], CFG) == near_low
    assert match_station(_lake(61.19, -149.78, None), [hill, near_low, far], CFG) == near_low
    # a lake up high doesn't take a town volunteer's snow; the hillside station is close in height
    assert match_station(_lake(61.12, -149.69, 600.0), [hill, near_low], CFG) == hill
    assert match_station(_lake(60.0, -151.0, 40.0), [hill, near_low, far], CFG) is None


def _day(d, snow=0.0, rain=0.0):
    return DayWeather(d, -3, 1, -1, snow, rain, 20.0)


def test_measured_snow_replaces_model_and_zeroes_rain_that_day():
    days = [_day(date(2026, 11, 18), rain=5.2), _day(date(2026, 11, 19), rain=21.6),
            _day(date(2026, 11, 20), snow=2.0)]
    out = apply_measured(days, {date(2026, 11, 19): 16.8, date(2026, 11, 20): 0.0})
    assert out[0] == days[0]                                   # no report: unchanged
    assert (out[1].snowfall_cm, out[1].rain_mm) == (16.8, 0.0)  # it snowed, not rained
    assert out[2].snowfall_cm == 0.0                          # measured nothing new


def test_latest_measured_snow_in_the_last_week():
    obs = {date(2026, 11, 10): 5.0, date(2026, 11, 16): 3.0, date(2026, 11, 19): 16.8, date(2026, 11, 20): 0.0}
    assert latest_measured(obs, date(2026, 11, 21), 7) == (date(2026, 11, 19), 16.8)
    assert latest_measured({date(2026, 11, 1): 4.0}, date(2026, 11, 21), 7) is None


@responses.activate
def test_fetch_survives_one_source_down():
    responses.add(responses.GET, snowobs.SNOTEL_URL_RE, body=SNOTEL)
    responses.add(responses.GET, snowobs.COCORAHS_URL, status=503)
    stations, obs = snowobs.fetch_observations(requests.Session(), date(2026, 10, 1), date(2026, 11, 21), CFG)
    assert {s.source for s in stations} == {"SNOTEL"}


@responses.activate
def test_fetch_all_down_returns_nothing():
    responses.add(responses.GET, snowobs.SNOTEL_URL_RE, status=500)
    responses.add(responses.GET, snowobs.COCORAHS_URL, body="<html>oops")
    assert snowobs.fetch_observations(requests.Session(), date(2026, 10, 1), date(2026, 11, 21), CFG) == ([], {})
