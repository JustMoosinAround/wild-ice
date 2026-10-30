# Wild Ice Finder — Design

Date: 2026-10-25
Status: Draft for review

## 1. Purpose

Tell one skater (the owner) when lakes in Southcentral Alaska are frozen but
not yet snow-covered, so they can go wild ice skating — replacing the current
manual process of scanning Sentinel-2 true-color imagery in Copernicus Browser
and picking lakes at random.

**Success:** the owner gets a phone alert when a reachable lake likely has
bare ice, opens a map, sees why the app thinks so plus the latest image, and
decides whether to go. Alerts are rare enough to trust and early enough to act on.

**Non-goals**
- Certifying ice as safe. The app shows a rough thickness estimate only; the
  owner makes every safety call.
- Multiple users, accounts, or regions outside Southcentral Alaska.
- Machine learning in v1 (ratings are collected now so it can be added later).

## 2. Decisions made

| Topic | Decision |
|---|---|
| Users | Owner only |
| Region | Southcentral Alaska (bounding box in config) |
| Lake selection | Automatic from OpenStreetMap, filtered; owner can pin and hide |
| Lake filters | Area ≥ 20 acres AND (≤ 2 mi from a drivable road OR ≤ 1 mi from a mapped trail) |
| Detection approach | Weather first, satellite confirms |
| Notification | ntfy phone push linking to the map |
| Map | Static web page on GitHub Pages, phone-friendly |
| Ratings | "Rate this lake" buttons, saved to the repo |
| Runtime | Daily GitHub Actions job |
| Language / libraries | Python pipeline; Leaflet map |
| Cost target | $0 |

## 3. Architecture

One GitHub repository holds the code, config, generated data, and the map site.

```
lake catalog (monthly) ──► lakes.geojson
                               │
daily job: weather ─► shortlist ─► imagery stats ─► score ─► publish ─► alert
                                                              │
                                                     data/status.json ──► map page
                                                                             │
                                                         ratings ◄── rate buttons
```

### 3.1 Units

Each unit is a separate Python module with a small, testable interface.

| Unit | Input | Output | Depends on |
|---|---|---|---|
| `catalog` | config bbox + filters | `data/lakes.geojson` | OSM Overpass API |
| `weather` | lakes, date | per-lake daily series: min/max/mean temp, snowfall, rain, wind gust | Open-Meteo |
| `icemodel` | daily weather series, prior state | thickness estimate, snow-since-reset, reset events | none (pure) |
| `imagery` | shortlisted lakes, date window | per-lake stats: S2 band means, NDSI, valid fraction, S1 VV backscatter | Copernicus Data Space (Sentinel Hub Statistical API) |
| `score` | ice model state + imagery stats + config | label, confidence, reason | none (pure) |
| `publish` | scores, history | `data/status.json`, `data/history/` | none |
| `alert` | today's vs. previous labels | one ntfy push (or none) | ntfy |
| `site/` | `status.json`, `lakes.geojson` | map UI, rating writes | Leaflet, GitHub API |

`icemodel` and `score` are pure functions: no network, no files. They hold all
the judgment and get the most tests.

### 3.2 Config (`config.yaml`)

All thresholds live here so they can be tuned after real outings:

- `region.bbox`
- `filters.min_area_acres: 50` (raised from 20 on 2026-10-29 to drop small ponds), `filters.max_road_miles: 2`, `filters.max_trail_miles: 1`
- `pinned: [lake ids]`, `hidden: [lake ids]`
- `ice.ashton_h: 20` (W/m²/K, ice-to-air heat transfer), `ice.skate_cm: 10`, `ice.open_cm: 2`
- `snow.cover_cm: 2`
- `reset.rain_mm`, `reset.thaw_days`, `reset.wind_gust_kmh`, `reset.light_snow_cm`
- `imagery.min_valid_fraction: 0.7`, `imagery.fresh_days: 3`, `imagery.shore_buffer_m`
- `imagery.snow_ndsi`, `imagery.snow_brightness`, `imagery.dark_brightness`
- `ntfy.topic_alerts`, `ntfy.topic_ops`, `site.base_url`

Values for reset thresholds and imagery brightness cutoffs are set during the
backtest (section 7); the initial values are placeholders in config only, not in code.

## 4. Data flow

### 4.1 Lake catalog (monthly, or on demand)

1. Query OSM for water polygons (`natural=water`, `water=lake|pond|reservoir`) in the bbox.
2. Drop polygons under 20 acres.
3. Query OSM drivable roads (`highway` values usable by cars) and trails
   (`highway=path|track|footway|bridleway`, snowmobile routes).
4. Keep a lake if its nearest edge is ≤ 2 mi from a road or ≤ 1 mi from a trail.
5. Add pinned lakes regardless of filters; remove hidden ones from alerting
   (they still appear greyed on the map).
6. Compute the interior polygon (shrunk inward by `shore_buffer_m`). Skip lakes
   whose interior is too small for at least ~20 Sentinel-2 pixels; pinned lakes
   in this state show a warning instead.
7. Write `data/lakes.geojson`: id (OSM id), name, area, road distance, trail
   distance, interior geometry.

### 4.2 Daily job

1. **Weather.** Group lakes into grid cells (Open-Meteo resolution) and fetch
   each cell once: daily min/max/mean temperature, snowfall, rain, max wind gust.
   Covers the season to date plus today.
2. **Ice model** (per lake, see section 5.1–5.2): update thickness,
   snow-since-reset, and reset events.
3. **Shortlist.** Lakes with estimated thickness ≥ `open_cm` and not already
   confidently snow-covered with no possible reset. Pinned lakes always included.
4. **Imagery.** For shortlisted lakes, request statistics over the interior for
   the last few days: Sentinel-2 L2A (B03, B04, B08, B11, SCL cloud mask, NDSI)
   and Sentinel-1 GRD VV backscatter.
5. **Score** (section 5.3–5.4).
6. **Publish.** Write `data/status.json` (current label, confidence, reason,
   thickness, last clear image date, Copernicus Browser deep link) and append
   to `data/history/`. Commit to the repo; GitHub Pages serves it.
7. **Alert** (section 5.5).

## 5. Scoring rules

### 5.1 Ice thickness

- Daily freezing degree-days: `FDD_day = max(0, 0 − T_mean)` (°C).
- Thaw days (T_mean > 0) subtract `T_mean` from the running total.
- Cumulative FDD is never below 0.
- Thickness estimate: Ashton (1989) thin-ice growth,
  `h = −k/H + √((k/H)² + 2·k·FDD/(ρ·L))` with ice conductivity k = 2.24 W/m/K,
  density ρ = 917 kg/m³, latent heat L = 334 kJ/kg and `H = ice.ashton_h` = 20.
  About 25 °C·days → ~10 cm. (Revised 2026-10-28: the earlier Stefan rule
  `2.0 × √FDD` credited 1.3 cm of ice after one −0.4 °C day, so snow that fell
  into still-open Ewan Lake was counted as snow on the ice.)
- **Freeze-up** = the day the estimate first reaches `ice.open_cm` (the lake
  "catches"). Snow before that falls into open water or onto skim ice and is
  not counted. The lake stays caught until the estimate returns to 0 (full
  melt); the next catch is a new freeze-up.
- Thickness carries through the winter; it does not reset with surface resets.

### 5.2 Surface and resets

- `snow_since_reset_cm` sums daily snowfall after the most recent reset
  (freeze-up counts as the first reset).
- Reset events, strongest first:
  1. **Seen** (confirmed): a clear S2 image shows the lake dark after a prior
     clear image or the weather model showed it white.
  2. **Rain/thaw then refreeze** (likely): rain ≥ `reset.rain_mm` or ≥
     `reset.thaw_days` above freezing, followed by a return to freezing.
  3. **Wind after light snow** (possible): gust ≥ `reset.wind_gust_kmh` after
     snowfall ≤ `reset.light_snow_cm`.
- Confirmed and likely resets set `snow_since_reset_cm = 0`.
- Possible resets are shown on the map but do not reset the counter or alert.

### 5.3 Reading the imagery

- S2 image counts only if valid (cloud-free per SCL) fraction ≥ 0.7.
- Surface class from a valid S2 image:
  - **White** (snow): NDSI ≥ `snow_ndsi` and brightness ≥ `snow_brightness`
  - **Dark** (water or clear ice): brightness ≤ `dark_brightness`
  - **Grey** (frost, thin snow, mixed): anything between
- S1 VV backscatter is compared with that lake's own pre-freeze baseline; it is
  used as supporting evidence of frozen vs. open when S2 is dark or unavailable.
  It never overrides a clear S2 white reading.
- At low sun (December), S2 may be missing or unusable; the app falls back to
  weather + S1 and lowers confidence.

### 5.4 Labels and confidence

Evaluated in this order; first match wins:

| Label | Rule |
|---|---|
| **Open water** | `h_cm < 2` |
| **Snow-covered** | Latest valid S2 is White, or `snow_since_reset_cm > 2` with no valid S2 since the snowfall |
| **Freezing** | `2 ≤ h_cm < 10` |
| **Likely black ice** | `h_cm ≥ 10`, `snow_since_reset_cm ≤ 2`, and latest valid S2 is Dark or S1 indicates frozen |
| **Unknown** | Everything else (for example no valid imagery and conflicting signals) |

Confidence:
- **High** — valid S2 within `fresh_days` (3)
- **Medium** — older S2, or S1 only, or reset type "likely"
- **Low** — weather only

Each label carries a one-line reason, for example:
"~14 cm est., no snow since rain on Jan 9, dark on Jan 12 S2 image."

### 5.5 Alerts

- At most one push per morning to `ntfy.topic_alerts`.
- It lists lakes that **newly** became Likely black ice since the previous run,
  pinned lakes first. Hidden lakes never alert.
- A lake alerts again only after it leaves the label and later returns
  (for example after a reset).
- Each entry links to the map with that lake selected (`site.base_url/#lake=<id>`).

## 6. Map

- Leaflet map, phone-first layout, served from GitHub Pages.
- Lakes colored by label; hidden lakes greyed.
- Filter toggle: show only Likely black ice / Freezing.
- Lake panel: label, confidence, reason, thickness estimate, short history
  (last ~14 days of labels), latest true-color thumbnail, link to Copernicus
  Browser at that lake and image date.
- **Rate this lake:** skated it / snow / water / rough ice. Each rating saves
  lake id, date, rating, optional note.
- Ratings are saved by calling the GitHub API with a fine-grained personal
  access token (scoped to this repo, contents write) entered once and kept in
  the phone browser's local storage. Ratings append to `data/ratings/`.
- If saving fails (no signal), the rating waits in local storage and retries on
  the next page load.
- Pin / hide buttons in the panel write to the same place and are applied on
  the next run.

## 7. Failure handling

| Failure | Behavior |
|---|---|
| Open-Meteo or Copernicus unavailable | Retry with backoff; if still failing, keep previous labels, mark map "data from <date>", send one push to `ntfy.topic_ops` |
| Copernicus free-tier quota near limit | Prioritize pinned lakes, then largest; log usage each run |
| Clouds or no image | Label falls back per section 5.4 (often Unknown); not an error |
| Lake interior too small | Skipped at catalog time; pinned ones show a warning |
| GitHub Actions job crash | GitHub's failure email plus ops push from a final step |
| Rating save fails | Queued locally, retried |

## 8. Testing

- **Unit tests for `icemodel` and `score`** with synthetic weather series:
  cold week → expected thickness; 3 cm snow → Snow-covered; rain then refreeze
  → counter reset; thaw days shrink thickness; White S2 overrides everything.
- **Recorded fixtures** of real Overpass, Open-Meteo, and Copernicus responses
  for a few lakes, so parsing and the full daily job run offline.
- **Backtest on last winter (main validation).** The owner provides lakes and
  dates when they skated (or found snow or water). Replay the pipeline over
  last season and compare. Tune thresholds in config until alerts line up.
- **Map:** manual check on the owner's phone.

## 9. Setup the owner provides

- GitHub account and repo (Actions + Pages enabled)
- Copernicus Data Space account and OAuth client (stored as Actions secrets)
- ntfy app on phone, subscribed to two private topic names
- Fine-grained GitHub token for ratings, entered once on the phone
- A list of known skating/snow dates for the backtest

## 10. Later (not v1)

- Learn from ratings (classifier on imagery + weather features).
- Texture analysis of full-resolution imagery for cracks and patterns.
