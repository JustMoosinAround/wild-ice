# Wild Ice Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily job that flags Southcentral Alaska lakes likely to have bare, snow-free ice, publishes a phone-friendly map, and sends one ntfy push when a lake newly qualifies.

**Architecture:** A Python package (`wildice`) runs once a day in GitHub Actions: weather (Open-Meteo) drives a pure ice/surface model, a shortlist of plausible lakes gets Sentinel-2/Sentinel-1 statistics from Copernicus Data Space, a pure scorer labels each lake, and results are written as JSON into `site/`, which GitHub Pages serves as a Leaflet map. Ratings and pin/hide taps from the map are written back to the repo as small JSON files through the GitHub API.

**Tech Stack:** Python 3.12, requests, shapely ≥ 2, pyproj, PyYAML, osm2geojson, pytest, responses (HTTP mocking); Leaflet 1.9.4 (CDN); Node 20 built-in test runner for the one JS module with logic; GitHub Actions + Pages; ntfy.sh.

**Spec:** `docs/superpowers/specs/2026-10-25-wild-ice-finder-design.md`

## Global Constraints

- Single user; region is Southcentral Alaska. Default bbox `(south, west, north, east) = (59.3, -152.5, 62.8, -144.0)`.
- Lake filter: area ≥ 20 acres AND (≤ 2 mi from a drivable road OR ≤ 1 mi from a mapped trail). Pinned lakes bypass filters.
- Every threshold lives in `config.yaml`; code never hard-codes a threshold. Initial values: `ice.alpha 2.0`, `ice.skate_cm 10`, `ice.open_cm 2`, `snow.cover_cm 2`, `reset.rain_mm 5`, `reset.thaw_days 2`, `reset.wind_gust_kmh 60`, `reset.light_snow_cm 5`, `imagery.min_valid_fraction 0.7`, `imagery.fresh_days 3`, `imagery.shore_buffer_m 30`, `imagery.snow_ndsi 0.4`, `imagery.snow_brightness 0.3`, `imagery.dark_brightness 0.12`, `imagery.s1_frozen_delta_db 3.0`, `imagery.lookback_days 14`, `imagery.monthly_request_budget 9000`, `season_start "10-01"`. Reset and imagery cutoffs are placeholders to be tuned by the backtest (Task 12).
- All dates are local dates in `America/Anchorage`. `run_date` = today in that zone.
- The app never states ice is safe. Thickness is always shown as "est." with the disclaimer text `Rough estimate only — check ice yourself.`
- Secrets come from environment variables only: `CDSE_CLIENT_ID`, `CDSE_CLIENT_SECRET`, `NTFY_TOPIC_ALERTS`, `NTFY_TOPIC_OPS`. The repo is public (free Pages), so topic names are never committed.
- Label string values (used in JSON and JS): `open_water`, `freezing`, `likely_black_ice`, `snow_covered`, `unknown`. Confidence values: `high`, `medium`, `low`.
- Lake ids: `w<osm way id>` or `r<osm relation id>`.
- Cost target $0; at most one alert push per morning.

## Review Focus

1. **A lake that spans two Overpass tiles** comes back twice — expect it once in the catalog (dedupe by id). Test in Task 5.
2. **Open-Meteo returns `null` for today's partial day or a missing value** — expect that day dropped if `t_mean` is null and other nulls read as 0.0, never a crash and never a fake 0 °C day. Test in Task 6.
3. **Sentinel-2 returns no intervals at all in December (low sun)** — expect an empty observation list and a weather/radar-only label, not an error or a `stale` page. Test in Task 7.
4. **The phone saves a rating while the daily job is pushing** — expect the job's push to rebase and retry, never lose the rating file. Test in Task 10 (workflow push script).
5. **An unnamed lake** — expect it shown and alerted as `Unnamed lake (34 ac)`, not `None`. Test in Task 8.

---

## File Structure

```
pyproject.toml
config.yaml
backtest.yaml                     # owner's known dates (Task 12)
wildice/
  __init__.py
  config.py        # load_config -> Config
  models.py        # dataclasses + enums shared by all modules
  geo.py           # projections, area, interior, distances
  catalog.py       # Overpass fetch + build_catalog + read/write lakes.geojson
  weather.py       # Open-Meteo fetch, parse, cache
  icemodel.py      # PURE: thickness, freeze-up, resets, snow counter
  score.py         # PURE: classify_s2, s1_frozen, score_lake
  imagery.py       # Copernicus client, budget, fetch_imagery, baseline, thumbnail
  evalscripts/s2_stats.js, s1_stats.js, truecolor.js
  prefs.py         # pinned/hidden from config + phone event files
  shortlist.py     # which lakes get imagery
  publish.py       # status.json, history, browser link, display name
  alert.py         # new-lake detection, ntfy
  run_daily.py     # orchestrator CLI
  backtest.py      # replay a past season
scripts/push_with_retry.sh
.github/workflows/daily.yml, catalog.yml, test.yml
site/index.html, site/style.css, site/app.js, site/ratings.js
site/data/        # generated: lakes.geojson, status.json, history/, thumbs/
state/            # generated: weather/, alert_state.json, baselines.json, usage.json
ratings/          # written by phone
prefs/            # written by phone
tests/            # pytest, fixtures/; tests/js/ratings.test.mjs
```

---

### Task 1: Project scaffold, config, shared models

**Files:**
- Create: `pyproject.toml`, `config.yaml`, `wildice/__init__.py`, `wildice/config.py`, `wildice/models.py`, `.gitignore`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces (`wildice/config.py`):
  - `class ConfigError(Exception)`
  - Frozen dataclasses `RegionCfg(bbox: tuple[float,float,float,float])`, `FiltersCfg(min_area_acres, max_road_miles, max_trail_miles)`, `IceCfg(alpha, skate_cm, open_cm)`, `SnowCfg(cover_cm)`, `ResetCfg(rain_mm, thaw_days: int, wind_gust_kmh, light_snow_cm)`, `ImageryCfg(min_valid_fraction, fresh_days: int, shore_buffer_m, snow_ndsi, snow_brightness, dark_brightness, s1_frozen_delta_db, lookback_days: int, monthly_request_budget: int)`, `SiteCfg(base_url: str)`, `Config(region, filters, ice, snow, reset, imagery, site, season_start: str, pinned: tuple[str,...], hidden: tuple[str,...])`
  - `load_config(path: Path) -> Config`
- Produces (`wildice/models.py`):
  - `class Label(StrEnum)`: `OPEN_WATER="open_water"`, `FREEZING="freezing"`, `LIKELY_BLACK_ICE="likely_black_ice"`, `SNOW_COVERED="snow_covered"`, `UNKNOWN="unknown"`
  - `class Confidence(StrEnum)`: `HIGH`, `MEDIUM`, `LOW` (lowercase values)
  - `class SurfaceClass(StrEnum)`: `WHITE`, `DARK`, `GREY`
  - `class ResetKind(StrEnum)`: `FREEZE_UP="freeze_up"`, `CONFIRMED="confirmed"`, `LIKELY="likely"`, `POSSIBLE="possible"`
  - Frozen dataclasses:
    - `Lake(id: str, name: str|None, area_acres: float, road_mi: float|None, trail_mi: float|None, lat: float, lon: float, interior: dict|None, warning: str|None)` — `interior` is a GeoJSON geometry in EPSG:4326
    - `DayWeather(day: date, t_min: float, t_max: float, t_mean: float, snowfall_cm: float, rain_mm: float, gust_kmh: float)`
    - `ResetEvent(day: date, kind: ResetKind)`
    - `IceState(cum_fdd: float, thickness_cm: float, freeze_up: date|None, last_reset: ResetEvent|None, snow_since_reset_cm: float, last_snow_day: date|None, possible_resets: tuple[ResetEvent,...])`
    - `S2Obs(day: date, valid_fraction: float, b03: float, b04: float, b11: float)`
    - `S1Obs(day: date, vv_db: float)`
    - `ImageryStats(s2: tuple[S2Obs,...], s1: tuple[S1Obs,...], s1_baseline_db: float|None)`
    - `Score(lake_id: str, label: Label, confidence: Confidence, reason: str, thickness_cm: float, last_clear_day: date|None)`

- [ ] **Step 1:** `git init`; write `pyproject.toml` (project `wildice`, Python ≥ 3.12, deps and dev deps from Tech Stack, pytest `testpaths=["tests"]`), `.gitignore` (`.venv/`, `__pycache__/`, `.pytest_cache/`), and `config.yaml` with every key and initial value from Global Constraints, `site.base_url: "https://<github-user>.github.io/wild-ice"`, `pinned: []`, `hidden: []`. Run `pip install -e .[dev]`.

- [ ] **Step 2: Write failing tests** in `tests/test_config.py`:

```python
def test_loads_repo_config():
    cfg = load_config(Path("config.yaml"))
    assert cfg.filters.max_road_miles == 2
    assert cfg.filters.max_trail_miles == 1
    assert cfg.ice.skate_cm == 10
    assert cfg.snow.cover_cm == 2
    assert cfg.imagery.min_valid_fraction == 0.7
    assert cfg.region.bbox == (59.3, -152.5, 62.8, -144.0)

def test_missing_key_raises(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text("ice: {alpha: 2.0}\n")
    with pytest.raises(ConfigError, match="filters"):
        load_config(p)

def test_pinned_ids_are_tuple(tmp_path): ...  # pinned: [w1, r2] -> ("w1", "r2")
```

- [ ] **Step 3:** Run `pytest tests/test_config.py -v` → FAIL (import error).
- [ ] **Step 4:** Implement `config.py` and `models.py` per Interfaces. `ConfigError` message names the missing top-level or nested key.
- [ ] **Step 5:** Run `pytest -v` → PASS.
- [ ] **Step 6:** Commit `feat: scaffold, config and shared models`.

---

### Task 2: Ice model — thickness and freeze-up

**Files:**
- Create: `wildice/icemodel.py`
- Test: `tests/test_icemodel_thickness.py`

**Interfaces:**
- Consumes: `Config`, `DayWeather`, `IceState`, `ResetEvent`, `ResetKind`, `SurfaceClass` (Task 1)
- Produces: `run_ice_model(days: Sequence[DayWeather], cfg: Config, s2_classes: Mapping[date, SurfaceClass] | None = None) -> IceState` — `days` sorted ascending, season to date.

Test helper in each icemodel test file: `def wx(day_offset, t_mean, snow=0.0, rain=0.0, gust=0.0)` building a `DayWeather` from `date(2025,11,1) + timedelta(day_offset)` with `t_min=t_mean-3`, `t_max=t_mean+3`.

- [ ] **Step 1: Write failing tests:**

```python
def test_cold_week_thickness():          # 7 days at -5  -> cum 35, h = 2*sqrt(35)
    s = run_ice_model([wx(i, -5) for i in range(7)], cfg)
    assert s.cum_fdd == 35
    assert s.thickness_cm == pytest.approx(11.83, abs=0.01)

def test_thaw_subtracts_mean():          # 5 x -5 then +3 -> cum 22
    s = run_ice_model([wx(i, -5) for i in range(5)] + [wx(5, 3)], cfg)
    assert s.cum_fdd == 22
    assert s.thickness_cm == pytest.approx(9.38, abs=0.01)

def test_never_negative():
    s = run_ice_model([wx(i, 4) for i in range(4)], cfg)
    assert s.cum_fdd == 0 and s.thickness_cm == 0 and s.freeze_up is None

def test_freeze_up_is_first_reset():
    s = run_ice_model([wx(0, 1), wx(1, -2)], cfg)
    assert s.freeze_up == date(2025, 11, 2)
    assert s.last_reset == ResetEvent(date(2025, 11, 2), ResetKind.FREEZE_UP)

def test_full_melt_then_new_freeze_up():
    s = run_ice_model([wx(0, -2), wx(1, 3), wx(2, -1)], cfg)
    assert s.freeze_up == date(2025, 11, 3)

def test_empty_days():
    s = run_ice_model([], cfg)
    assert s.thickness_cm == 0 and s.freeze_up is None
```

- [ ] **Step 2:** Run `pytest tests/test_icemodel_thickness.py -v` → FAIL.
- [ ] **Step 3:** Implement `run_ice_model` as a single day-by-day loop: `cum = max(0, cum + (-t_mean))` (cold days add `-t_mean`, warm days subtract `t_mean`), `h = alpha * sqrt(cum)`; freeze-up when `h` goes from 0 to > 0 (sets `last_reset` to `FREEZE_UP` and zeroes the snow counter). Leave the surface/reset logic for Task 3, but structure the loop so it slots in.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: ice thickness model and freeze-up`.

---

### Task 3: Ice model — snow counter and resets

**Files:**
- Modify: `wildice/icemodel.py`
- Test: `tests/test_icemodel_resets.py`

**Interfaces:**
- Consumes/Produces: same `run_ice_model` signature as Task 2.

Daily order inside the loop (decided here so behavior is unambiguous):
1. Update thickness / freeze-up (Task 2).
2. If frozen, check resets in strength order — seen (from `s2_classes[day]`), then rain/thaw-then-refreeze, then wind. A confirmed or likely reset sets `snow_since_reset_cm = 0`, clears `possible_resets` and the "seen white" flag.
3. Then add that day's `snowfall_cm` to the counter (if frozen), and set `last_snow_day` when > 0.

Rules:
- **Seen (CONFIRMED):** `s2_classes[day] == DARK` and (`snow_since_reset_cm > cover_cm`, or a WHITE was seen since the last reset, or `last_reset.kind == LIKELY`). `WHITE` sets the "seen white" flag.
- **Likely:** today `t_mean <= 0`, previous day `t_mean > 0`, and the warm run that just ended had ≥ `thaw_days` consecutive days, or its total `rain_mm` ≥ `reset.rain_mm`.
- **Possible:** `gust_kmh >= wind_gust_kmh` and `0 < snow_since_reset_cm <= light_snow_cm` → append `ResetEvent(day, POSSIBLE)`; counter unchanged.
- Snowfall before freeze-up is ignored.

- [ ] **Step 1: Write failing tests** (10 cold days at -5 as base unless noted):

```python
def test_snow_accumulates_after_freeze_up():          # 1.5 cm day 3, 1.0 cm day 5
    assert s.snow_since_reset_cm == pytest.approx(2.5)
    assert s.last_snow_day == date(2025, 11, 6)

def test_snow_before_freeze_up_ignored():             # [wx(0, 2, snow=4)] + cold
    assert s.snow_since_reset_cm == 0

def test_rain_then_refreeze_is_likely_reset():
    # cold 0-4, snow 3 on day 3, day 5 t=+1 rain=6, day 6 t=-3
    assert s.last_reset == ResetEvent(date(2025, 11, 7), ResetKind.LIKELY)
    assert s.snow_since_reset_cm == 0

def test_two_thaw_days_then_refreeze_is_likely_reset(): # days 5,6 at +1 no rain, day 7 -3
    assert s.last_reset.kind == ResetKind.LIKELY

def test_one_dry_warm_day_is_not_reset():
    assert s.last_reset.kind == ResetKind.FREEZE_UP

def test_wind_after_light_snow_is_possible():          # snow 3 day 3, gust 70 day 5
    assert s.possible_resets == (ResetEvent(date(2025, 11, 6), ResetKind.POSSIBLE),)
    assert s.snow_since_reset_cm == 3

def test_wind_after_heavy_snow_is_not_possible():      # snow 8 day 3, gust 70 day 5
    assert s.possible_resets == ()

def test_dark_image_after_snow_confirms_reset():       # snow 3 day 3; s2 DARK day 5
    assert s.last_reset == ResetEvent(date(2025, 11, 6), ResetKind.CONFIRMED)
    assert s.snow_since_reset_cm == 0

def test_dark_image_without_prior_snow_is_not_reset():
    assert s.last_reset.kind == ResetKind.FREEZE_UP

def test_white_then_dark_confirms_reset():             # WHITE day 4, DARK day 6, no weather snow
    assert s.last_reset.kind == ResetKind.CONFIRMED

def test_dark_after_likely_reset_upgrades_to_confirmed():
    assert s.last_reset.kind == ResetKind.CONFIRMED
```

- [ ] **Step 2:** Run `pytest tests/test_icemodel_resets.py -v` → FAIL.
- [ ] **Step 3:** Implement the rules above in `icemodel.py`.
- [ ] **Step 4:** Run `pytest -v` → all PASS (Task 2 tests still pass).
- [ ] **Step 5:** Commit `feat: snow counter and reset detection`.

---

### Task 4: Scoring — surface class, radar, labels, confidence, reason

**Files:**
- Create: `wildice/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: `Config`, `Lake`, `IceState`, `ImageryStats`, `S2Obs`, `S1Obs`, enums (Task 1)
- Produces:
  - `classify_s2(obs: S2Obs, cfg: Config) -> SurfaceClass | None` — `None` when `valid_fraction < min_valid_fraction`. `brightness = (b03 + b04) / 2`; `ndsi = (b03 - b11) / (b03 + b11)` (0 when the denominator is 0). WHITE if `ndsi >= snow_ndsi and brightness >= snow_brightness`; DARK if `brightness <= dark_brightness`; else GREY.
  - `valid_s2_classes(imagery: ImageryStats | None, cfg: Config) -> dict[date, SurfaceClass]` — the input `run_ice_model` takes.
  - `s1_frozen(obs: S1Obs, baseline_db: float | None, cfg: Config) -> bool | None` — `None` without baseline; True when `vv_db - baseline_db >= s1_frozen_delta_db`.
  - `score_lake(lake: Lake, ice: IceState, imagery: ImageryStats | None, run_date: date, cfg: Config) -> Score`

Label rules, first match wins (spec 5.4, with Open water first):
1. `h < open_cm` → OPEN_WATER
2. latest valid S2 is WHITE, or (`snow_since_reset_cm > cover_cm` and no valid S2 dated after `last_snow_day`) → SNOW_COVERED
3. `h < skate_cm` → FREEZING
4. `snow_since_reset_cm <= cover_cm` and (latest valid S2 is DARK, or (no valid S2 in the lookback window and latest S1 is frozen)) → LIKELY_BLACK_ICE
5. else UNKNOWN

Confidence: HIGH if a valid S2 within `fresh_days` of `run_date`; MEDIUM if an older valid S2 or any S1; LOW otherwise. LIKELY_BLACK_ICE is capped at MEDIUM when `last_reset.kind == LIKELY`.

Reason: `"; "`-joined parts — `~{h:.0f} cm est.`, then the snow part (`no snow since <reset phrase> on <Mon D>` or `{snow:.0f} cm snow since <Mon D>`), then the evidence part (`dark on <Mon D> image`, `white on <Mon D> image`, `radar shows ice`, or `no clear image since <Mon D>` / `no clear image`), then — only when `ice.possible_resets` is non-empty — `possible wind clearing <Mon D>` for the latest one (this is how the map shows possible resets). Format dates as `f"{d:%b} {d.day}"` (portable). Reset phrases: freeze_up → `freeze-up`, confirmed → `clearing`, likely → `rain/thaw`.

- [ ] **Step 1: Write failing tests:**

```python
def test_classify_white(): assert classify_s2(S2Obs(D, .9, .6, .6, .1), cfg) is SurfaceClass.WHITE
def test_classify_dark():  assert classify_s2(S2Obs(D, .9, .05, .04, .02), cfg) is SurfaceClass.DARK
def test_classify_grey():  assert classify_s2(S2Obs(D, .9, .2, .2, .1), cfg) is SurfaceClass.GREY
def test_classify_cloudy_none(): assert classify_s2(S2Obs(D, .5, .05, .04, .02), cfg) is None

def test_s1_frozen():  assert s1_frozen(S1Obs(D, -15), -20, cfg) is True
def test_s1_open():    assert s1_frozen(S1Obs(D, -19), -20, cfg) is False
def test_s1_no_baseline(): assert s1_frozen(S1Obs(D, -15), None, cfg) is None

def test_open_water():           # h=1
    assert score_lake(lake, ice(h=1), None, RUN, cfg).label is Label.OPEN_WATER
def test_snow_by_weather_low():  # h=12, snow 3, no imagery
    s = score_lake(...); assert (s.label, s.confidence) == (Label.SNOW_COVERED, Confidence.LOW)
def test_white_image_high():     # h=12, snow 0, WHITE 1 day before RUN
    assert (s.label, s.confidence) == (Label.SNOW_COVERED, Confidence.HIGH)
def test_freezing():             # h=6
    assert s.label is Label.FREEZING
def test_black_ice_fresh_dark_high():   # h=12, snow 0, DARK 1 day ago
    assert (s.label, s.confidence) == (Label.LIKELY_BLACK_ICE, Confidence.HIGH)
    assert "~12 cm est." in s.reason and "dark on" in s.reason
def test_black_ice_old_dark_medium():   # DARK 5 days ago
    assert s.confidence is Confidence.MEDIUM
def test_black_ice_radar_only_medium(): # no S2, S1 frozen
    assert (s.label, s.confidence) == (Label.LIKELY_BLACK_ICE, Confidence.MEDIUM)
def test_no_imagery_unknown_low():      # h=12, snow 0, imagery None
    assert (s.label, s.confidence) == (Label.UNKNOWN, Confidence.LOW)
def test_grey_is_unknown():             # latest valid S2 GREY
    assert s.label is Label.UNKNOWN
def test_likely_reset_caps_medium():    # last_reset LIKELY, DARK fresh
    assert s.confidence is Confidence.MEDIUM
def test_reason_dates_have_no_leading_zero():  # dark on Jan 5 -> "Jan 5"
def test_reason_mentions_possible_reset():     # possible_resets=(Nov 6 POSSIBLE,)
    assert "possible wind clearing Nov 6" in s.reason
```

- [ ] **Step 2:** Run `pytest tests/test_score.py -v` → FAIL.
- [ ] **Step 3:** Implement `score.py` per Interfaces and rules. `last_clear_day` = date of the latest valid S2.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: lake scoring and surface classification`.

---

### Task 5: Geometry and lake catalog

**Files:**
- Create: `wildice/geo.py`, `wildice/catalog.py`
- Test: `tests/test_geo.py`, `tests/test_catalog.py`, `tests/fixtures/overpass_water.json`, `tests/fixtures/overpass_roads.json`, `tests/fixtures/overpass_trails.json`

**Interfaces:**
- Consumes: `Config`, `Lake` (Task 1)
- Produces (`geo.py`, all inputs and outputs in EPSG:4326 except where noted; projection is EPSG:3338 Alaska Albers):
  - `area_acres(geom: BaseGeometry) -> float`
  - `interior(geom: BaseGeometry, buffer_m: float, min_area_m2: float = 2000) -> BaseGeometry | None` — inward buffer; `None` when the result is empty or under `min_area_m2` (≈ 20 Sentinel-2 pixels)
  - `class LineIndex` — `__init__(lines: list[BaseGeometry])`, `nearest_miles(geom: BaseGeometry) -> float | None` (shapely `STRtree` over projected lines; `None` if no lines)
- Produces (`catalog.py`):
  - `tiles(bbox, step: float = 1.0) -> list[tuple[float,float,float,float]]`
  - `overpass_query(kind: Literal["water","roads","trails"], bbox) -> str`
    - water: `way`/`relation` with `natural=water` and `water~"^(lake|pond|reservoir)$"` or no `water` tag
    - roads: `highway~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service)(_link)?$"`
    - trails: `highway~"^(path|track|footway|bridleway)$"` or `snowmobile~"^(yes|designated)$"`
    - all with `out geom;`
  - `fetch_osm(kind, bbox, session) -> list[dict]` — GeoJSON features via `osm2geojson.json2geojson`, over every tile, **deduplicated by `type`+`id`**; POST to `https://overpass-api.de/api/interpreter`, 180 s timeout, 3 retries with backoff
  - `build_catalog(water: list[dict], roads: list[dict], trails: list[dict], cfg: Config) -> list[Lake]` — applies the spec 4.1 filters; pinned ids from `cfg.pinned` are kept regardless of filters; lakes whose `interior` is `None` are dropped unless pinned, where `warning="Lake too narrow for satellite readings"`
  - `write_catalog(lakes: list[Lake], path: Path) -> None` / `load_catalog(path: Path) -> list[Lake]` — GeoJSON FeatureCollection; geometry = interior, properties = the other `Lake` fields
  - CLI: `python -m wildice.catalog` writes `site/data/lakes.geojson`

- [ ] **Step 1: Write failing tests:**

```python
# test_geo.py
def test_area_of_known_square():   # 0.01° x 0.01° box near 61N ≈ 0.6 km²
    assert area_acres(box) == pytest.approx(148, rel=0.05)
def test_interior_shrinks():       assert interior(box, 30).area < box.area
def test_interior_too_small_none():# 60 m wide strip, 30 m buffer -> None
def test_nearest_miles():          # point 0.02° east of a N-S line at 61N ≈ 0.67 mi
    assert LineIndex([line]).nearest_miles(pt) == pytest.approx(0.67, rel=0.05)

# test_catalog.py (fixtures: 4 lakes —
#   A 40 ac 1.5 mi from road; B 40 ac 3 mi from road, 0.5 mi from trail;
#   C 40 ac 3 mi from road, 3 mi from trail; D 10 ac next to road)
def test_filters():         assert {l.id for l in build_catalog(...)} == {"wA", "wB"}
def test_pinned_bypasses(): # cfg.pinned=("wC",) -> includes wC
def test_unnamed_name_none():  # lake with no name tag -> Lake.name is None
def test_tile_dedupe(responses): # same way returned by two tiles -> one feature
    assert len(fetch_osm("water", two_tile_bbox, session)) == 1
def test_catalog_roundtrip(tmp_path): assert load_catalog(p) == lakes
```

- [ ] **Step 2:** Run `pytest tests/test_geo.py tests/test_catalog.py -v` → FAIL.
- [ ] **Step 3:** Implement `geo.py` and `catalog.py` per Interfaces. `Lake.lat/lon` = representative point of the full polygon.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: OSM lake catalog with road/trail filters`.

---

### Task 6: Weather fetch and cache

**Files:**
- Create: `wildice/weather.py`
- Test: `tests/test_weather.py`, `tests/fixtures/openmeteo_two_cells.json`

**Interfaces:**
- Consumes: `Config`, `DayWeather` (Task 1)
- Produces:
  - `season_start(run_date: date, cfg: Config) -> date` — the most recent `season_start` (`MM-DD`) on or before `run_date`
  - `cell_of(lat: float, lon: float) -> tuple[float, float]` — rounded to 0.1°
  - `parse_location(daily: dict) -> list[DayWeather]` — one Open-Meteo `daily` block
  - `fetch_daily(cells: list[tuple[float,float]], start: date, end: date, session, archive: bool) -> dict[tuple[float,float], list[DayWeather]]` — batches of ≤ 50 coordinates per request; archive → `https://archive-api.open-meteo.com/v1/archive` with `start_date/end_date`; else `https://api.open-meteo.com/v1/forecast` with `past_days=14&forecast_days=1`. Daily vars: `temperature_2m_min,temperature_2m_max,temperature_2m_mean,snowfall_sum,rain_sum,wind_gusts_10m_max`; `timezone=America/Anchorage`. Forecast results are trimmed to days ≤ `end`.
  - `update_cache(cache_dir: Path, cells, run_date: date, cfg: Config, session) -> dict[tuple[float,float], list[DayWeather]]` — per-cell JSON at `cache_dir/<lat>_<lon>.json`. A cell with no cache is backfilled from `season_start` with the archive API, then merged with the forecast API; existing cells only call the forecast API. Merge by date, newer values overwrite.

- [ ] **Step 1: Write failing tests:**

```python
def test_season_start_before_oct(): assert season_start(date(2026,2,1), cfg) == date(2025,10,1)
def test_season_start_after_oct():  assert season_start(date(2026,11,5), cfg) == date(2026,10,1)
def test_cell_rounding():            assert cell_of(60.7725, -148.7965) == (60.8, -148.8)
def test_parse_drops_null_mean():    # last day temperature_2m_mean null -> dropped
    assert [d.day for d in parse_location(block)] == [date(2025,11,1), date(2025,11,2)]
def test_parse_null_snow_is_zero():  assert days[0].snowfall_cm == 0.0
def test_fetch_batches(responses):   # 120 cells -> 3 requests
def test_cache_backfills_then_merges(tmp_path, responses):
    # first call hits archive + forecast; second call only forecast; overlapping day takes forecast value
```

- [ ] **Step 2:** Run `pytest tests/test_weather.py -v` → FAIL.
- [ ] **Step 3:** Implement per Interfaces. Sessions use `urllib3.Retry(total=3, backoff_factor=2, status_forcelist=[429,500,502,503,504])`; after retries, raise `SourceUnavailable("open-meteo")` (define `class SourceUnavailable(Exception)` in `wildice/models.py` with `source: str`).
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: Open-Meteo weather fetch with season cache`.

---

### Task 7: Copernicus imagery client and request budget

**Files:**
- Create: `wildice/imagery.py`, `wildice/evalscripts/s2_stats.js`, `wildice/evalscripts/s1_stats.js`, `wildice/evalscripts/truecolor.js`
- Test: `tests/test_imagery.py`, `tests/fixtures/cdse_s2_stats.json`, `tests/fixtures/cdse_s2_empty.json`, `tests/fixtures/cdse_s1_stats.json`

**Interfaces:**
- Consumes: `Config`, `Lake`, `S2Obs`, `S1Obs`, `ImageryStats`, `SourceUnavailable` (Tasks 1, 6)
- Produces:
  - `class CopernicusClient(client_id: str, client_secret: str, session)`:
    - token via client-credentials POST to `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`, cached until expiry
    - `s2_stats(geometry: dict, start: date, end: date) -> list[S2Obs]`
    - `s1_stats(geometry: dict, start: date, end: date) -> list[S1Obs]`
    - `truecolor_png(geometry: dict, day: date) -> bytes`
    - Statistics: POST `https://sh.dataspace.copernicus.eu/api/v1/statistics` with `aggregationInterval P1D`, collection `sentinel-2-l2a` / `sentinel-1-grd`, geometry CRS `http://www.opengis.net/def/crs/EPSG/0/4326`. Process (thumbnail): `https://sh.dataspace.copernicus.eu/api/v1/process`, 256×256 PNG.
    - Every request calls `self.budget.record()` when a `Budget` is attached.
  - `s2_stats.js` outputs bands `B03, B04, B11` and `valid` (1 where SCL ∉ {0,1,3,8,9,10}) with `dataMask`; `valid_fraction` = mean of `valid`; band means are over valid pixels only. A day with no valid pixels gives `valid_fraction=0`.
  - `s1_stats.js` outputs VV linear; the client converts the mean to dB (`10*log10`).
  - `class Budget(path: Path, monthly_limit: int)`: `remaining() -> int`, `record(n: int = 1) -> None`, `save() -> None`; the count resets when the stored month ≠ current month.
  - `fetch_imagery(client, lake: Lake, run_date: date, cfg: Config, baseline_db: float | None) -> ImageryStats` — window `run_date - lookback_days .. run_date`
  - `s1_baseline(client, lake: Lake, freeze_up: date) -> float | None` — median VV dB over the 30 days before `freeze_up`; `None` if no observations

- [ ] **Step 1: Write failing tests:**

```python
def test_s2_parse(responses):          # fixture: 2 intervals
    obs = client.s2_stats(geom, D1, D2)
    assert obs[0] == S2Obs(date(2025,11,3), 0.92, 0.051, 0.043, 0.020)
def test_s2_empty_is_empty_list(responses):  # December: {"data": []}
    assert client.s2_stats(geom, D1, D2) == []
def test_s1_db_conversion(responses):  # linear 0.01 -> -20 dB
    assert client.s1_stats(geom, D1, D2)[0].vv_db == pytest.approx(-20.0)
def test_token_reused(responses):      # two stats calls -> one token request
def test_http_500_raises_source_unavailable(responses):
    with pytest.raises(SourceUnavailable): client.s2_stats(...)
def test_budget_resets_monthly(tmp_path): # stored month 2025-10, now 2025-11 -> remaining == limit
def test_budget_counts_requests(tmp_path, responses): # 2 calls -> remaining == limit - 2
```

- [ ] **Step 2:** Run `pytest tests/test_imagery.py -v` → FAIL.
- [ ] **Step 3:** Implement per Interfaces. Capture one real response of each kind by hand (with the owner's credentials) to build the fixtures, trimmed to two intervals.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: Copernicus statistics client and request budget`.

---

### Task 8: Prefs, shortlist, publish

**Files:**
- Create: `wildice/prefs.py`, `wildice/shortlist.py`, `wildice/publish.py`
- Test: `tests/test_prefs.py`, `tests/test_shortlist.py`, `tests/test_publish.py`

**Interfaces:**
- Consumes: `Config`, `Lake`, `IceState`, `Score`, `Label`, `ResetKind` (Tasks 1, 4)
- Produces:
  - `load_prefs(cfg: Config, prefs_dir: Path) -> tuple[frozenset[str], frozenset[str]]` — (pinned, hidden). Start from `cfg.pinned/hidden`, apply each `prefs/*.json` (`{"lake_id": ..., "action": "pin"|"unpin"|"hide"|"unhide"}`) in filename order.
  - `shortlist(lakes: list[Lake], ice: dict[str, IceState], pinned: frozenset[str], cfg: Config, remaining_requests: int) -> list[str]` — included: pinned, plus lakes with `thickness_cm >= open_cm` and not (`snow_since_reset_cm > cover_cm` and no reset or possible reset after `last_snow_day`). Order: pinned first, then by `area_acres` descending. Truncate so that `2 * len(result) <= remaining_requests` (one S2 plus one S1 request per lake).
  - `display_name(lake: Lake) -> str` — name, or `f"Unnamed lake ({lake.area_acres:.0f} ac)"`
  - `browser_url(lat: float, lon: float, day: date | None) -> str` — `https://browser.dataspace.copernicus.eu/?zoom=14&lat=..&lng=..&themeId=DEFAULT-THEME&datasetId=S2_L2A_CDAS&layerId=1_TRUE_COLOR&dateMode=SINGLE&fromTime=<day>T00:00:00.000Z&toTime=<day>T23:59:59.999Z` (time params omitted when `day` is None)
  - `build_status(lakes, scores: dict[str, Score], pinned, hidden, history: dict[str, list[dict]], run_date: date, stale_since: date | None) -> dict` — schema:

```json
{"run_date": "2025-11-12", "stale_since": null,
 "disclaimer": "Rough estimate only — check ice yourself.",
 "lakes": {"w123": {"name": "...", "label": "likely_black_ice", "confidence": "high",
   "reason": "...", "thickness_cm": 12.0, "last_clear_day": "2025-11-11",
   "browser_url": "...", "thumb": "thumbs/w123.png" , "pinned": true, "hidden": false,
   "warning": null, "history": [{"day": "2025-11-11", "label": "freezing"}]}}}
```

  - `load_history(history_dir: Path, run_date: date, days: int = 14) -> dict[str, list[dict]]` — reads `history/<YYYY-MM-DD>.json` files (each `{lake_id: label}`)
  - `write_outputs(status: dict, site_data: Path, run_date: date) -> None` — writes `status.json` and `history/<run_date>.json`; `thumb` is set only when `site_data/thumbs/<id>.png` exists

- [ ] **Step 1: Write failing tests:**

```python
def test_prefs_apply_in_order(tmp_path):   # pin w1, hide w2, unpin w1 -> ({}, {"w2"})
def test_prefs_config_base(tmp_path):      # cfg.pinned=("w9",), no files -> ({"w9"}, {})
def test_shortlist_skips_open_and_snowed():
def test_shortlist_keeps_snowed_with_possible_reset():
def test_shortlist_pinned_first_then_area():
def test_shortlist_truncates_to_budget():  # remaining 4 -> 2 lakes
def test_display_name_unnamed():
    assert display_name(Lake(id="w1", name=None, area_acres=34.2, ...)) == "Unnamed lake (34 ac)"
def test_browser_url_has_date():
    assert "fromTime=2025-11-11T00:00:00.000Z" in browser_url(61.0, -149.0, date(2025,11,11))
def test_status_schema(tmp_path):          # keys and disclaimer text exactly as above
def test_stale_since_written(tmp_path):
def test_history_window(tmp_path):         # 20 files -> only last 14 days loaded
```

- [ ] **Step 2:** Run `pytest tests/test_prefs.py tests/test_shortlist.py tests/test_publish.py -v` → FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: prefs, shortlist and status publishing`.

---

### Task 9: Alerts

**Files:**
- Create: `wildice/alert.py`
- Test: `tests/test_alert.py`

**Interfaces:**
- Consumes: `Lake`, `Score`, `Label`, `display_name` (Tasks 1, 8)
- Produces:
  - `newly_black_ice(scores: dict[str, Score], prev_labels: dict[str, str], lakes: dict[str, Lake], pinned: frozenset[str], hidden: frozenset[str]) -> list[str]` — ids now `LIKELY_BLACK_ICE` whose previous label was anything else (or absent); hidden excluded; pinned first, then by area descending
  - `format_alert(ids: list[str], lakes, scores, pinned, base_url: str) -> tuple[str, str, str]` — (title, markdown body, click URL). Title: `"1 lake looks skateable"` / `"3 lakes look skateable"`. Body: one line per lake `- [★ ]**<display name>** — <reason> ([map](<base_url>/#lake=<id>))` (★ for pinned). Click: the first lake's map URL.
  - `send_ntfy(topic: str, title: str, body: str, click: str | None, session) -> None` — POST `https://ntfy.sh/<topic>`, headers `Title`, `Markdown: yes`, `Click` (if given)
  - `load_labels(path: Path) -> dict[str, str]` / `save_labels(path: Path, scores: dict[str, Score]) -> None` — `state/alert_state.json`

- [ ] **Step 1: Write failing tests:**

```python
def test_new_lake_alerts():            # prev freezing -> now likely
def test_unchanged_lake_silent():      # prev likely -> now likely -> []
def test_returns_after_leaving():      # prev snow_covered -> now likely -> alerts
def test_hidden_never_alerts():
def test_pinned_first():
def test_title_plural(): assert format_alert(two_ids, ...)[0] == "2 lakes look skateable"
def test_body_has_map_link(): assert "/#lake=w1)" in body
def test_send_ntfy_headers(responses): # Title, Markdown: yes, Click present
```

- [ ] **Step 2:** Run `pytest tests/test_alert.py -v` → FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** Commit `feat: ntfy alerts for newly skateable lakes`.

---

### Task 10: Daily orchestrator, failure handling, workflows

**Files:**
- Create: `wildice/run_daily.py`, `scripts/push_with_retry.sh`, `.github/workflows/daily.yml`, `.github/workflows/catalog.yml`, `.github/workflows/test.yml`
- Test: `tests/test_run_daily.py`, `tests/test_push_with_retry.py` (runs the bash script via `subprocess` against temporary git repos)

**Interfaces:**
- Consumes: everything above.
- Produces: `run(run_date: date, root: Path, env: Mapping[str, str], session, client: CopernicusClient | None = None) -> int` (exit code) and CLI `python -m wildice.run_daily [--date YYYY-MM-DD]`.

`run` sequence (spec 4.2):
1. `cfg = load_config`, `lakes = load_catalog(site/data/lakes.geojson)`, `pinned, hidden = load_prefs`.
2. `wx = update_cache(state/weather, cells, ...)`; per lake `ice0 = run_ice_model(wx[cell_of(lake)], cfg)`.
3. `ids = shortlist(..., remaining_requests=budget.remaining())`.
4. For each id: baseline from `state/baselines.json` keyed `"<lake_id>:<freeze_up>"`, else `s1_baseline` and store; `imagery = fetch_imagery(...)`; `ice = run_ice_model(..., valid_s2_classes(imagery, cfg))`.
5. `score_lake` for every lake (imagery `None` when not shortlisted).
6. Thumbnails: for lakes labeled `likely_black_ice` or `freezing` whose `last_clear_day` changed since the previous status, write `site/data/thumbs/<id>.png` (skip when the budget is exhausted).
7. `write_outputs`; `newly_black_ice` → `send_ntfy(NTFY_TOPIC_ALERTS, ...)` only if non-empty; `save_labels`; `budget.save()`.
8. On `SourceUnavailable`: keep the previous `status.json` lakes, set `stale_since` (the existing value, or the `run_date` of the last good run), write it, send `send_ntfy(NTFY_TOPIC_OPS, "Wild ice job failed", "<source> unavailable", None)`, return 1. Any other exception: send the same ops push with the exception type, then re-raise.

`scripts/push_with_retry.sh`: `git add -A site/data state && git commit -m "data: <date>" || exit 0`, then up to 5 times `git pull --rebase --autostash origin main && git push && exit 0`, sleeping 5 s between tries; exit 1 after 5 failures.

Workflows:
- `daily.yml`: `schedule: cron "0 17 * * *"` (≈ 8–9 am Alaska) + `workflow_dispatch`; checkout, setup-python 3.12, `pip install .`, `python -m wildice.run_daily` with the four secrets as env, `scripts/push_with_retry.sh`, then `actions/upload-pages-artifact` (path `site`) and `actions/deploy-pages`. A final step `if: failure()` posts to the ops topic with curl. Permissions: `contents: write`, `pages: write`, `id-token: write`.
- `catalog.yml`: `cron "0 12 1 * *"` + `workflow_dispatch`; runs `python -m wildice.catalog`, then the push script.
- `test.yml`: on push/PR: `pytest -q` and `node --test tests/js/`.

- [ ] **Step 1: Write failing tests** (all HTTP mocked with `responses`, Copernicus via a fake client object exposing the Task 7 methods):

```python
def test_happy_path_writes_status_and_alerts(tmp_repo, responses):
    assert run(RUN, tmp_repo, ENV, session, fake_client) == 0
    status = json.loads((tmp_repo/"site/data/status.json").read_text())
    assert status["lakes"]["w1"]["label"] == "likely_black_ice"
    assert ntfy_calls(responses, "alerts-topic") == 1
def test_second_run_same_result_no_alert(...): assert ntfy_calls(...) == 1   # still 1 after 2 runs
def test_no_candidates_no_push(...):           assert ntfy_calls(...) == 0
def test_weather_down_marks_stale_and_pings_ops(...):
    assert run(...) == 1
    assert status["stale_since"] == "2025-11-11"   # previous good run date
    assert status["lakes"] == previous["lakes"]
    assert ntfy_calls(responses, "ops-topic") == 1
def test_baseline_cached(...):                 # second run makes no s1_baseline call
def test_budget_exhausted_skips_imagery(...):  # remaining 0 -> fake_client never called; labels from weather only
```

```python
# test_push_with_retry: creates a bare "origin", clones A (job) and B (phone);
# B pushes ratings/x.json after A commits; running the script in A succeeds
# and origin/main contains both A's site/data change and ratings/x.json.
```

- [ ] **Step 2:** Run `pytest tests/test_run_daily.py tests/test_push_with_retry.py -v` → FAIL.
- [ ] **Step 3:** Implement `run_daily.py`, the push script and the three workflows.
- [ ] **Step 4:** Run `pytest -v` → all PASS. Lint workflows with `actionlint` if available, otherwise check by hand that every secret name matches Global Constraints.
- [ ] **Step 5:** Commit `feat: daily orchestrator, failure handling and workflows`.

---

### Task 11: Map site and ratings

**Files:**
- Create: `site/index.html`, `site/style.css`, `site/app.js`, `site/ratings.js`
- Test: `tests/js/ratings.test.mjs`

**Interfaces:**
- Consumes: `site/data/lakes.geojson` (Task 5), `site/data/status.json` (Task 8)
- Produces (`site/ratings.js`, ES module, no dependencies):
  - `buildRatingFile(lakeId, rating, note, now: Date) -> {path, content}` — `path = "ratings/<ISO date>-<epoch ms>-<lakeId>.json"`, `content` = JSON `{lake_id, day, rating, note}`; `rating ∈ {"skated","snow","water","rough"}` (throws otherwise)
  - `buildPrefFile(lakeId, action, now) -> {path, content}` — `prefs/<epoch ms>-<lakeId>.json`, action ∈ pin/unpin/hide/unhide
  - `saveFile(file, {token, repo}, fetchFn) -> Promise<void>` — `PUT https://api.github.com/repos/<repo>/contents/<path>` with base64 content, `Authorization: Bearer <token>`; rejects on non-2xx
  - `enqueue(storage, file)`, `flushQueue(storage, creds, fetchFn) -> Promise<number>` (count saved; failed items stay queued, order kept). Queue key `wildice.queue`; creds key `wildice.creds`.

UI (`app.js`, `index.html`, `style.css`) — checked by hand:
- Leaflet 1.9.4 from `https://unpkg.com/leaflet@1.9.4/dist/`; OSM tiles.
- Lake polygons colored by label: open_water blue `#3b82f6`, freezing teal `#14b8a6`, likely_black_ice dark navy with a bright outline `#0f172a`/`#facc15`, snow_covered white `#f8fafc` with a grey outline, unknown grey `#9ca3af`; hidden lakes at 30% opacity. Pinned lakes get a ★ marker.
- Toggle: "Only skateable / freezing".
- Banner when `stale_since` is set: `Data from <stale_since> — the daily job failed.`
- `#lake=<id>` opens that lake's panel and zooms to it.
- Panel: name, label, confidence, reason, `est. <n> cm` + disclaimer, 14-day history strip, thumbnail if present, "Open in Copernicus Browser" link, rating buttons (skated / snow / water / rough + optional note), Pin/Hide toggles.
- First rating with no stored creds shows a one-time form (token, `owner/repo`) saved to localStorage.
- `flushQueue` runs on page load and after each tap.

- [ ] **Step 1: Write failing tests** (`node:test`, fake `storage` = Map-backed object, fake `fetchFn`):

```js
test("rating file path and content", () => {
  const f = buildRatingFile("w1", "skated", "glassy", new Date("2025-11-12T18:00:00Z"));
  assert.match(f.path, /^ratings\/2025-11-12-\d+-w1\.json$/);
  assert.deepEqual(JSON.parse(f.content), {lake_id: "w1", day: "2025-11-12", rating: "skated", note: "glassy"});
});
test("bad rating throws", ...);
test("saveFile sends PUT with base64 and bearer token", ...);
test("failed save stays queued", async () => { /* fetch 500 -> flush returns 0, queue length 1 */ });
test("queue flushes in order and keeps failures", ...);
```

- [ ] **Step 2:** Run `node --test tests/js/` → FAIL.
- [ ] **Step 3:** Implement `ratings.js`, then the UI.
- [ ] **Step 4:** Run `node --test tests/js/` → PASS. Create `tests/fixtures/sample_site/` (a `lakes.geojson` and `status.json` with one lake per label, one pinned, one hidden, `stale_since` set), copy it to `site/data/`, serve with `python -m http.server -d site`, and check at phone width: colors, panel, `#lake=` link, stale banner, rating queue while offline (devtools offline mode).
- [ ] **Step 5:** Commit `feat: map site with ratings and pin/hide`.

---

### Task 12: Backtest

**Files:**
- Create: `wildice/backtest.py`, `backtest.yaml`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `load_catalog`, `fetch_daily(archive=True)`, `run_ice_model`, `CopernicusClient`, `fetch_imagery`, `s1_baseline`, `valid_s2_classes`, `score_lake`.
- Produces:
  - `backtest.yaml`: `observations: [{lake_id: w123, day: 2025-12-03, observed: skated|snow|water|rough}]` (owner fills in; ship with one commented example)
  - `@dataclass Row(lake_id, day, observed, predicted: Label, confidence: Confidence, reason: str, match: bool)`
  - `EXPECTED = {"skated": {Label.LIKELY_BLACK_ICE}, "snow": {Label.SNOW_COVERED}, "water": {Label.OPEN_WATER, Label.FREEZING}, "rough": {Label.FREEZING, Label.UNKNOWN, Label.SNOW_COVERED}}`
  - `run_backtest(obs_path: Path, root: Path, session, client) -> list[Row]` — for each observation: archive weather from that season's start to `day`, imagery over `lookback_days` before `day`, score as of `day`
  - `summarize(rows) -> str` — table of rows plus `matched X/Y`, and counts of false alerts (predicted likely_black_ice where observed ≠ skated) and misses (observed skated, predicted otherwise)
  - CLI: `python -m wildice.backtest [backtest.yaml]`

- [ ] **Step 1: Write failing tests** (fake weather and fake client):

```python
def test_skated_day_matches():  # cold 20 days, no snow, DARK image -> match True
def test_snow_day_matches():    # 5 cm snow, no image -> snow_covered, match True
def test_false_alert_counted(): assert "false alerts: 1" in summarize(rows)
def test_miss_counted():        assert "misses: 1" in summarize(rows)
```

- [ ] **Step 2:** Run `pytest tests/test_backtest.py -v` → FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Run `pytest -v` → all PASS.
- [ ] **Step 5:** Commit `feat: backtest against known skating dates`.
- [ ] **Step 6 (with owner):** Owner fills `backtest.yaml` with last winter's dates; run `python -m wildice.backtest` with real credentials; adjust `config.yaml` thresholds (reset and imagery cutoffs first) until false alerts and misses are acceptable to the owner; commit `tune: thresholds from backtest`.

---

## Owner setup checklist (outside code, before the first scheduled run)

- Create a public GitHub repo; enable Actions and Pages (source: GitHub Actions).
- Copernicus Data Space account → create an OAuth client → add `CDSE_CLIENT_ID`, `CDSE_CLIENT_SECRET` as Actions secrets.
- Install ntfy on the phone; choose two hard-to-guess topic names; add as `NTFY_TOPIC_ALERTS`, `NTFY_TOPIC_OPS`.
- Set `site.base_url` in `config.yaml`.
- Create a fine-grained token (this repo only, Contents: read/write) and enter it on the map's first rating.
- Run the `catalog` workflow once by hand, then `daily`.
