# Explore App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the map site into a skating app: Explore feed of lakes that are in (five sort chips, badges, evidence line), Map tab, full lake page with a timeline, My lakes, and GPX/FIT track upload.

**Architecture:** The daily Python job adds per-lake fields to `status.json` (came_in, last_report, featured_photo, timeline). The Worker gains saved lakes, a skated list, track reports and featured photos in its export. The site gets pure, node-tested modules (`explore.js`, `track.js`) plus DOM views wired into `app.js` behind a bottom tab bar.

**Tech Stack:** Python 3.12 (pytest), Cloudflare Worker + D1 (vitest), static ES modules + Leaflet 1.9.4 (node --test), no build step.

**Spec:** `docs/superpowers/specs/2026-11-22-explore-app-design.md`

## Global Constraints

- Free only: GitHub Pages, Cloudflare free plan, no paid APIs, no new CDN libraries (FIT is decoded by our own code).
- No new phone notifications; "Just in" is in-app only.
- Friends' names and notes never go into `status.json`; grades, rating, day may.
- Works at 360 px width; touch targets ≥ 44 px; existing routes `#lake=`, `#review`, `#invite=`, `#skateable` keep working (`#skateable` opens Explore).
- `JUST_IN_DAYS = 3`. Sort chips, in order: `just_in` (default), `best_ice`, `biggest`, `new_to_you`, `adventures`.
- Hike-in badge when `road_mi > 0.5` and `trail_mi <= 1`; shown as `Hike-in ~{road_mi:.1f} mi`.
- Upload matching = skatelog rules: ≥ 10 min on the lake and ≥ 30 % of moving time, gaps > 300 s not counted, day in America/Anchorage.
- The raw track never leaves the phone: send lake, day, minutes, one point.
- Track reports store `gps_source = 'device'` plus `track_minutes` (avoids rebuilding the `reports` table's CHECK constraint); `track_minutes IS NOT NULL` means "from a track".

## Review Focus

1. A lake whose history has a one-day dip (in, unknown, in) should keep its original `came_in` day, not reset to the dip's end. Test in Task 1.
2. A track that crosses two catalog lakes, or none, should show every qualifying lake to pick from, or "No catalog lake on this track", never silently pick one. Test in Task 5.
3. A GPX with no timestamps, or a `.fit.gz` that isn't gzip, should give a readable error, not a blank screen. Test in Task 5.
4. A lake with no `last_clear_day` and no report must still render a card ("No clear image yet") and sort last within its chip. Test in Task 4.
5. A non-member opening My lakes or Upload sees saved-on-this-phone lakes / a join prompt; no Worker call without a device key. Test in Task 7.

---

### Task 1: Status fields from the daily job

**Files:**
- Create: `wildice/explore.py`
- Modify: `wildice/publish.py` (`build_status`), `wildice/run_daily.py` (pass the new inputs), `wildice/icelog.py` (`Export.featured`)
- Test: `tests/test_explore.py`, `tests/test_publish.py`

**Interfaces:**
- Produces (Python): `came_in(history: list[dict], label: str, run_date: date) -> date | None`;
  `timeline(report: Report | None, classes: Mapping[date, SurfaceClass], snow: tuple[date, float, str] | None, reset: ResetEvent | None, limit: int = 8) -> list[dict]` (dicts `{day, kind, text}`, newest first);
  `Export.featured: list[dict]` (`{lake_id, public_id, created_at}`).
- Produces (status.json, per lake): `came_in` (ISO or null), `last_report` (`{day, rating, grade}` or null), `featured_photo` (public id or null), `timeline` (list).

- [ ] **Step 1: Write the failing tests** in `tests/test_explore.py`:
  - `test_came_in_is_first_day_of_current_in_run`: history labels `snow, snow, likely_black_ice, likely_black_ice` + today `likely_black_ice` → came_in = first `likely_black_ice` day.
  - `test_came_in_survives_a_one_day_dip`: `likely, unknown, likely` + today likely → the first likely day (Review Focus 1).
  - `test_came_in_none_when_not_in`: today `snow_covered` → None; `rough_ice` counts as in.
  - `test_timeline_newest_first_and_capped`: report Nov 21 skated B+, classes {Nov 20: CRACKED, Nov 12: WHITE}, snow (Nov 18, 8.0, "Willow"), reset CONFIRMED Nov 20 → texts `"Skated (B+)"`, `"Crack network seen"`, `"8 cm new snow at Willow"`, `"White (snow) on image"`; limit honoured.
  - `test_timeline_has_no_names_or_notes`: Report with note "secret" → "secret" not in any text.
- [ ] **Step 2: Run** `pytest tests/test_explore.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** `came_in` and `timeline` in `wildice/explore.py`. A dip of one non-in day between in-days does not break the run; two or more do.
- [ ] **Step 4: Run** `pytest tests/test_explore.py -v` → PASS.
- [ ] **Step 5: Failing test** `tests/test_publish.py::test_status_carries_explore_fields`: `build_status(..., explore={"w1": {...}})` puts `came_in`, `last_report`, `featured_photo`, `timeline` on lake w1 and nulls/[] on others.
- [ ] **Step 6: Implement**: `build_status(..., explore: Mapping[str, dict] | None = None)`; in `run_daily` build per lake from `reports`, `optical_classes(...)`, `latest_measured`, `ice.last_reset`, `export.featured` (newest per lake). `fetch_export` parses `featured` (missing key → []).
- [ ] **Step 7: Run** `pytest -q` → all pass.
- [ ] **Step 8: Commit** `feat: status.json carries came_in, last_report, featured_photo and a timeline`.

### Task 2: Worker: saved lakes, skated list, track reports, featured export

**Files:**
- Create: `worker/migrations/0002_explore.sql`, `worker/src/saved.js`, `worker/test/saved.test.js`
- Modify: `worker/src/index.js` (routes), `worker/src/reports.js` (track_minutes, export featured)
- Test: `worker/test/saved.test.js`, `worker/test/reports.test.js`

**Interfaces:**
- Produces (HTTP, device key required unless noted):
  `GET /api/saved` → `{lakes: [lake_id]}`; `POST /api/saved {lake_id}` → `{ok:true}`; `DELETE /api/saved/:lake_id` → `{ok:true}`;
  `GET /api/me/skated` → `{lakes: [{lake_id, day}]}` (this friend's skated/rough reports, newest day per lake);
  `POST /api/reports` accepts `track_minutes` (integer 10–1440, requires `gps`);
  `GET /api/export` (service token) adds `featured: [{lake_id, public_id, created_at}]` and `track_minutes` on report rows.
- Migration: `CREATE TABLE saved (friend_id TEXT NOT NULL, lake_id TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (friend_id, lake_id));` and `ALTER TABLE reports ADD COLUMN track_minutes INTEGER;`

- [ ] **Step 1: Failing tests**: save → list contains it; save twice is one row; delete removes; another friend's list is separate; revoked device → 401; `/api/me/skated` lists only own skated/rough lakes; report with `track_minutes: 5` → 400, `track_minutes: 42` without gps → 400, with gps → 200 and appears in export with `track_minutes: 42`; export includes featured photos only (not pending/rejected).
- [ ] **Step 2: Run** `cd worker && npx vitest run` → new tests FAIL.
- [ ] **Step 3: Implement** migration, `saved.js` handlers, report/export changes. Lake ids validated with the existing lake-id pattern.
- [ ] **Step 4: Run** `npx vitest run` → all pass.
- [ ] **Step 5: Apply the migration** `CLOUDFLARE_API_TOKEN=proxy-injected npx wrangler d1 migrations apply <db> --remote` and deploy `npx wrangler deploy`; check `GET /api/saved` without a key → 401.
- [ ] **Step 6: Commit** `feat(worker): saved lakes, skated list, track reports, featured photos in export`.

### Task 3: Python reads track reports

**Files:** Modify `wildice/icelog.py`, `wildice/reports.py` (`Report.track_minutes: int | None = None`). Test `tests/test_icelog.py`.

**Interfaces:** Consumes Task 2 export rows. Produces `Report.track_minutes`.

- [ ] **Step 1: Failing test** `test_track_report_is_verified_and_kept`: export row with `track_minutes: 42` and gps on the lake → Report verified "ok", `track_minutes == 42`; far gps → `no_gps`-style rejection as today.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `pytest -q` → pass.
- [ ] **Step 5: Commit** `feat: track reports from the Worker export`.

### Task 4: Explore logic module (pure)

**Files:** Create `site/explore.js`; Test `tests/js/explore.test.mjs`. Replaces `site/skatelist.js` (delete it and its test; move `skateMeta`/`shortDate` here).

**Interfaces:**
- Produces: `inLakes(lakes) -> [{id, ...d}]` (label `likely_black_ice`/`rough_ice`, not hidden);
  `isJustIn(d, runDate) -> bool` (`came_in` within 3 days and no `last_report` with rating skated/rough on or after `came_in`);
  `badges(d, props, ctx) -> string[]` where `props = {area_acres, road_mi, trail_mi}` and `ctx = {runDate, skated: Set<id>}`;
  `evidenceLine(d, runDate) -> {text, old: bool}` (`old` when the freshest evidence is > 7 days old);
  `sortLakes(list, chip, props, ctx) -> list`;
  `CHIPS = [{id:"just_in",label:"Just in"},{id:"best_ice",label:"Best ice"},{id:"biggest",label:"Biggest"},{id:"new_to_you",label:"New to you"},{id:"adventures",label:"Adventures"}]`.

- [ ] **Step 1: Failing tests:**
  - `badges`: came in yesterday, no report → includes `"Just in · no tracks yet"`; last_report B+ → `"Last grade B+"`; area 1600 → `"1,600 ac"`; not in skated → `"New to you"` (omitted when `ctx.skated` is null); road 3.5 trail 0 → `"Hike-in ~3.5 mi"`; road 0.2 → no hike badge.
  - `evidenceLine`: report yesterday B+ → `"Skated yesterday (B+)"`; timeline top CRACKED Nov 20 → `"Crack network seen Nov 20"`; only last_clear_day Nov 5 with runDate Nov 22 → `{text:"Satellite Nov 5", old:true}`; nothing → `"No clear image yet"` (Review Focus 4).
  - `sortLakes`: just_in newest came_in first, non-just-in after by freshest evidence; best_ice A+ before B and ungraded last; biggest by area; new_to_you unskated first; adventures by road_mi desc for hike-in lakes, others last; lakes without evidence last in every chip; pinned first in every chip.
- [ ] **Step 2: Run** `node --test "tests/js/*.test.mjs"` → FAIL.
- [ ] **Step 3: Implement** `site/explore.js`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(site): explore logic: just in, badges, evidence line, five sorts`.

### Task 5: Track parsing and lake matching (pure)

**Files:** Create `site/track.js`; Test `tests/js/track.test.mjs`.

**Interfaces:**
- Produces: `parseGpx(text) -> Point[]`; `parseFit(arrayBuffer) -> Point[]` (record messages, fields 0 lat / 1 lon semicircles, 253 timestamp, FIT epoch 1989-12-31; handles compressed-timestamp headers by skipping); `readTrackFile(file) -> Promise<Point[]>` (`.gz` via `DecompressionStream("gzip")`); `matchLakes(points, features) -> [{lakeId, name, minutes, share, day, point}]` sorted by minutes desc, only those meeting ≥ 10 min and ≥ 30 %.
  `Point = {lat, lon, t}` (t = ms since epoch). Errors thrown as `TrackError` with a readable message.
- Point-in-polygon on the lake feature geometry (Polygon/MultiPolygon, holes respected); `day` = Alaska date (`Intl` with `America/Anchorage`) of the middle point on the lake; `point` = that point.

- [ ] **Step 1: Failing tests:** GPX with 30 one-minute points on a square lake → one match, minutes 29, day correct in Alaska time across UTC midnight; FIT bytes built in the test (header, one definition, 30 records) → same points; track over two lakes → two matches sorted (Review Focus 2); track off all lakes → `[]`; GPX without `<time>` → `TrackError("This track has no times")`; non-gzip `.fit.gz` → `TrackError("Couldn't read this file")` (Review Focus 3); gaps > 300 s not counted.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(site): read GPX/FIT tracks and match them to lakes`.

### Task 6: App shell and Explore view

**Files:** Create `site/views/explore-view.js`; Modify `site/index.html` (tab bar, view containers), `site/app.js` (routing, tabs, remove `showSkateable`/`addSkateButton`), `site/style.css`.

**Interfaces:**
- Consumes Task 4 (`inLakes`, `badges`, `evidenceLine`, `sortLakes`, `CHIPS`).
- Produces: `showTab(name)` in app.js for `"explore" | "map" | "mine" | "upload"`; hash `#tab=<name>`; `#skateable` → explore. `renderExplore(mount, {status, props, ctx, openLake, onToggleMap})`.
- Card photo: `featured_photo` → `${WORKER_URL}/api/photos/<id>`, else `d.thumb`; lazy-loaded; alt text is the lake name.
- Chip choice remembered in localStorage key `wildice.chip` (try/catch).

- [ ] **Step 1:** Build the tab bar and Explore list/map toggle; Map tab = today's map. Empty state: "Nothing looks in today" followed by up to 5 `freezing` lakes, thickest first.
- [ ] **Step 2: Verify** with Playwright at 390×844 (local Leaflet route as before): Explore shows cards with chips; tapping a chip reorders; List/Map toggles; `#skateable` lands on Explore; no console errors; screenshot to scratchpad.
- [ ] **Step 3: Run** `node --test "tests/js/*.test.mjs"` → pass.
- [ ] **Step 4: Commit** `feat(site): tab bar and Explore feed with sort chips`.

### Task 7: Lake page, saving, My lakes

**Files:** Create `site/views/lake-page.js`, `site/views/mine-view.js`; Modify `site/icelog.js` (`getSaved`, `setSaved`, `getSkated`, local fallback), `site/app.js`, `site/style.css`. Test `tests/js/icelog.test.mjs`.

**Interfaces:**
- Produces in `icelog.js`: `getSaved({fetch, storage, base}) -> Promise<string[]>`; `setSaved(lakeId, on, {...}) -> Promise<void>`; `getSkated({...}) -> Promise<{lake_id, day}[]>`. No device → saved in localStorage key `wildice.saved`, skated `[]`, and no fetch call (Review Focus 5).
- Lake page sections in order: hero photo + name + chip + badges; "What we know, and when" (`timeline`); report buttons (members); Field Notes; weather chart + colour strip + hazard notes + Copernicus link; Save toggle.

- [ ] **Step 1: Failing tests** in `icelog.test.mjs`: saved round-trip with a device (fetch called with Authorization); without a device: localStorage used and fetch never called; getSkated without device → `[]`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** client functions, lake page, My lakes (Saved list + Skated list with current status for each). **Step 4: Run** → PASS.
- [ ] **Step 5: Verify** with Playwright: lake page renders hero, timeline, Field Notes; save toggles; My lakes lists it.
- [ ] **Step 6: Commit** `feat(site): full lake page, saved lakes and My lakes`.

### Task 8: Upload view

**Files:** Create `site/views/upload-view.js`; Modify `site/app.js`, `site/icelog.js` (`makeReport` gains `trackMinutes`).

**Interfaces:** Consumes Task 5 (`readTrackFile`, `matchLakes`) and the existing report queue (`queueReport`, `flushReports`). `makeReport({..., trackMinutes})` sets `track_minutes` and `gps = {lat, lon, source:"device"}` from the match point.

- [ ] **Step 1: Failing test** `makeReport` with `trackMinutes: 42` and point → body has `track_minutes: 42`, `gps.source === "device"`.
- [ ] **Step 2: Implement** the view: file input (multiple; `.gpx,.fit,.gz`), per file: match list → pick lake (if several) → skated/rough + grade + note + optional photo → queue. Non-members see the join prompt instead. Multiple files let the owner seed history from the Strava export in one go.
- [ ] **Step 3: Run** node tests → pass; **Verify** with Playwright using a generated GPX over a catalog lake: match shown, report queued.
- [ ] **Step 4: Commit** `feat(site): upload a GPX/FIT track as a trip report`.

### Task 9: Ship

- [ ] **Step 1:** `pytest -q`, `node --test "tests/js/*.test.mjs"`, `cd worker && npx vitest run` → all pass.
- [ ] **Step 2:** Push to `main` and `main-qj6jns`; trigger `daily.yml`; confirm the new status fields in `site/data/status.json` and the Pages deploy.
- [ ] **Step 3:** Phone-width screenshots of Explore, lake page, My lakes, Upload sent to the owner.
