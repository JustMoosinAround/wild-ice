# Measured snow from stations — design

Date: 2026-11-21 · Status: approved by the owner in conversation ("check the CoCoRaHS
download and then build it")

## Why
The weather model's snowfall is unreliable near freezing. Nov 18-19 2026: it recorded
27 mm of rain around Anchorage; the owner saw 4-8 in of wet snow, CoCoRaHS volunteers
measured 4-6.6 in new snow from only 5-10 mm of water, and SNOTEL depth jumped
(Anchorage Hillside 7 → 17 in). Measured snow should replace guessed snow where a
station is close enough. Free sources only; no image reading (webcams declined).

## Sources (free, no keys, same day)
- NRCS SNOTEL report generator CSV: all Alaska SNOTEL sites, daily start-of-day snow
  depth (in) and SWE (in), with lat/lon/elevation (ft).
- CoCoRaHS export CSV (data.cocorahs.org): Alaska daily reports with new snow (in),
  total depth, precipitation, lat/lon. A report on morning D covers the 24 h before,
  so its new snow belongs to day D-1.
- NOAA GHCN-Daily runs ~9 days late: not used daily (possible backtest source later).

## Rules
- New snow per station-day: CoCoRaHS NewSnowDepth (T = 0) → day D-1. SNOTEL:
  depth(D+1) - depth(D) when positive and SWE rose (or SWE missing) → day D.
- A lake uses its nearest station within 25 km whose elevation is within 300 m of the
  lake's (HydroLAKES elevation). Stations without an elevation (CoCoRaHS) and lakes
  without one are matched only when both are lowland (≤ 400 m, or unknown for the lake).
- On days the station reported, its new snow replaces the weather model's snowfall
  for that lake; measured snow > 0 also zeroes the model's rain that day (it fell as
  snow). Days without a report keep the weather model plus the wet-snow rule.
- A lake whose snow came from a station within the last week gets a note in its
  reason: "measured 17 cm new snow at Anchorage 4.5 E (CoCoRaHS), Nov 19".
- Fetch failures are logged and the run carries on with the weather model alone.
- Settings in config.yaml (`snowobs:`) for the owner's reset/snow tuning.

## Not in scope
Webcams; ground-vs-lake snow differences (wind scour); NOAA archive backtests.
