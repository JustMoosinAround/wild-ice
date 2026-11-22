# Wild Ice as a skating app: Explore feed, lake pages, My lakes, track upload

Status: draft for owner approval, 2026-11-22.

## Intent

The app's primary job is to show which lakes are **in** (skateable) right now. Conditions
change fast; today the crew waits for trip reports or risks a long drive to a lake
that's no good. The app should make the freshest evidence obvious before anyone drives.

The feel should be like a trail app (an explore feed you can flip to a map, rich
lake pages, saved lists, uploads), geared to skating. It borrows those general
patterns, not any other app's name, branding or visual style.

## Goals

- Home answers "what's in?" at a glance, with how fresh each lake's evidence is.
- Lakes can be ranked by what the crew actually picks on (owner): **ice quality**,
  **size** (bigger is usually better), **novelty**, **access** (a long approach can be
  the draw: Eagle and Symphony, 5 mi in), and **first tracks** on a lake that just
  came in.
- A track from a watch or Strava (GPX/FIT) can be uploaded as a trip report.
- Saved lakes ("My lakes").

## Non-goals

- Recording GPS tracks in the app.
- A native/app-store app, user accounts beyond today's invites, or paid services.
- Real trail-mileage routing (straight-line road distance is labelled "~").

## Anti-goals

- No extra phone notifications: "Just in" lives only in the app (owner). Pings stay
  as today (a lake newly looks skateable; review count rides along).
- Don't bury evidence age. A lake resting on a three-week-old image must look it.
- Nothing that costs money; nothing that breaks what works today (map, search,
  Field Notes, review page, invites, installable app).

## Constraints

- Static site on GitHub Pages (plain ES modules, Leaflet, no build step) plus the
  Cloudflare Worker + D1 (free plan). The daily Python job writes `site/data/status.json`.
- Phones are the main screen; layout must work at 360 px wide with 44 px touch targets.
- Friends' notes are never public; grades, lake, day are already public (in reasons).
- iPhone home-screen app has its own storage (invite paste already handles joining).

## Approaches considered

- **A. Grow the current site into the app (chosen by owner).** Bottom tabs, new views
  as ES modules on the existing data; Worker stores saved lakes and history. Free,
  incremental, nothing thrown away; more hand-written UI code.
- B. Rebuild the front end in a component framework. Tidier components, but a rewrite
  of map/search/Field Notes/review before anything new, and a build step.
- C. Native app. Closest feel, but $99/yr Apple, store review, much bigger build.

## Design

### Navigation

Bottom tab bar, fixed, four tabs: **Explore**, **Map**, **My lakes**, **Upload**.
The header keeps the title and search. Existing hash routes keep working
(`#lake=`, `#review`, `#invite=`, `#skateable` opens Explore).

### Explore (home)

Feed of lakes that are in: label `likely_black_ice` or `rough_ice`, not hidden.
A List / Map toggle shows the same set on the map.

Sort chips (one active; remembered per phone):

| Chip | Order | Notes |
|---|---|---|
| **Just in** (default) | newest "came in" day first | came in = first day of the current run of in-labels in `history`; within the last `JUST_IN_DAYS` (3) |
| Best ice | latest grade (A+ best), ungraded last | grades from reports this season, newest per lake |
| Biggest | area desc | |
| New to you | lakes you've never skated first, then by Just in | needs your history; hidden without one |
| Adventures | longest approach first | approach = `road_mi` for lakes reached by trail |

Card: photo, name, badges, one line of evidence.
- Photo: newest featured Field Notes photo, else the satellite thumbnail.
- Badges (all shown whatever the sort): `Just in · no tracks yet` (came in within
  3 days and no skated report since), `Last grade B+`, `1,600 ac`, `New to you`,
  `Hike-in ~3.5 mi` (road_mi > 0.5 and trail reaches it), `★` pinned.
- Evidence line, freshest source first: `Skated yesterday (B+)`, or
  `Crack network seen Nov 20`, or `Satellite Nov 5` (old evidence: muted, with age).

```
[Just in] [Best ice] [Biggest] [New to you] [Adventures]
┌───────────────────────────────────────────┐
│ [photo] Symphony Lake                ★    │
│ Just in · no tracks yet · New to you      │
│ Satellite Nov 20 · Hike-in ~3.5 mi        │
└───────────────────────────────────────────┘
```

Empty state: "Nothing looks in today" plus the lakes closest to coming in (freezing).

### Map tab

Today's map, all lakes, colour key, search. Tapping a lake opens the lake page.

### Lake page

Replaces the bottom-sheet card with a full page (still a sheet on wide screens):
1. Hero photo (same rule as cards) with name, label chip, badges.
2. **What we know, and when**: a short newest-first timeline from status data:
   reports (`Skated Nov 21, B+`; no names, as today), images (`Crack network seen Nov 20`,
   `White on Nov 12`), snow (`8 cm new snow Nov 18 at …`), thaws/resets.
3. Report buttons (members), Field Notes (photos, comments).
4. Weather chart, colour strip, hazard notes, Copernicus link, Save button.

### My lakes

- Saved lakes (heart/save on cards and lake pages), with their current status.
- "Skated" list: lakes you've skated (from your reports and uploaded tracks).
- Members: stored in the Worker per friend (sync across their phones).
  Non-members: saved lakes in browser storage only; no skated list or New to you.

### Upload

Pick a .gpx, .fit or .fit.gz file (members only).
1. Parsed on the phone (gzip via DecompressionStream; FIT via a small pinned
   parser library or a minimal decoder; GPX via DOMParser).
2. Match to catalog lakes the same way `wildice/skatelog.py` does (time on the lake
   ≥ 10 min and ≥ 30% of moving time); day in Alaska time.
3. Show "Symphony Lake, Nov 15 — 42 min on the ice". The user can pick another
   matched lake if the track crossed several.
4. The usual report form (skated/rough + grade + note + photo), sent with
   `gps_source: "track"` and the lake-crossing point. The raw track is not uploaded
   or stored (privacy, size); only lake, day, minutes and one point.
5. Counts as a skated report (verified) and adds the lake to your Skated list.

Owner seeding: the owner's Strava history (the local `skatelog` run) can be sent
once as uploads, so New to you works from day one.

### Data the Python job adds to status.json (per lake)

- `came_in`: first day of the current in-run (or null).
- `last_report`: `{day, rating, grade}` newest this season (no note, no name).
- `area_acres`, `road_mi`, `trail` (bool) are already in lakes.geojson.
- `featured_photo`: public id of the newest featured photo (from the Ice Log export).
- `timeline`: up to 8 newest events `{day, kind, text}` built from what the job
  already knows (reports, image classes, measured snow, resets).

### Worker additions

- Table `saved (friend_id, lake_id, created_at)`; `GET/POST/DELETE /api/saved`.
- `GET /api/me/skated`: lake ids + days from this friend's skated/rough reports.
- `gps_source` accepts `'track'`; reports may carry `track_minutes`.
- Migration `0002_explore.sql`. All within the free plan.

## Left to the builder

Card and tab visual design within the current style tokens; exact timeline wording;
the FIT decoding choice (pinned library vs minimal decoder); how "came in" handles a
one-day dip in history; page transitions. Keep tests in the existing three suites
(pytest, node JS tests, Worker vitest).

## Calls made without asking (owner to check)

- Just in = came in within 3 days; "no tracks yet" = no skated report since it came in.
- Adventures uses straight-line road distance, labelled "~".
- The raw uploaded track stays on the phone; only lake, day, minutes and one point
  are sent.
- Non-members get saved lakes on their phone only.
- Four tabs (Explore, Map, My lakes, Upload); Upload shows a join prompt to non-members.
