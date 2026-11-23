import { test } from "node:test";
import assert from "node:assert/strict";
import { CHIPS, badges, evidenceLine, inLakes, isJustIn, shortDate, skateMeta, sortLakes } from "../../site/explore.js";

const RUN = "2026-11-22";

test("chips in order", () => {
  assert.deepEqual(CHIPS.map((c) => c.id), ["just_in", "best_ice", "biggest", "new_to_you", "adventures"]);
});

test("inLakes keeps likely black ice and rough ice that aren't hidden", () => {
  const got = inLakes({ a: { label: "likely_black_ice" }, b: { label: "rough_ice" },
    c: { label: "freezing" }, d: { label: "likely_black_ice", hidden: true } });
  assert.deepEqual(got.map((l) => l.id), ["a", "b"]);
});

test("just in: came in within 3 days and nobody has skated it since", () => {
  assert.equal(isJustIn({ came_in: "2026-11-20" }, RUN), true);
  assert.equal(isJustIn({ came_in: "2026-11-19" }, RUN), false);
  assert.equal(isJustIn({ came_in: "2026-11-21", last_report: { day: "2026-11-21", rating: "skated" } }, RUN), false);
  assert.equal(isJustIn({ came_in: "2026-11-21", last_report: { day: "2026-11-15", rating: "skated" } }, RUN), true);
  assert.equal(isJustIn({ came_in: null }, RUN), false);
});

test("badges", () => {
  const d = { id: "a", came_in: "2026-11-21", last_report: { day: "2026-11-10", rating: "skated", grade: "B+" } };
  const props = { a: { area_acres: 1600.4, road_mi: 3.46, trail_mi: 0.02 } };
  assert.deepEqual(badges(d, props, { runDate: RUN, skated: new Set() }),
    ["Just in · no tracks yet", "Last grade B+", "1,600 ac", "New to you", "Approach ~3.5 mi"]);
  assert.deepEqual(badges({ id: "a" }, { a: { area_acres: 40, road_mi: 0.2, trail_mi: 0 } },
    { runDate: RUN, skated: null }), ["40 ac"]);
  assert.deepEqual(badges({ id: "a" }, { a: { area_acres: 40, road_mi: 0.2 } },
    { runDate: RUN, skated: new Set(["a"]) }), ["40 ac"]);
});

test("evidence line picks the freshest source and marks old evidence", () => {
  assert.deepEqual(evidenceLine({ last_report: { day: "2026-11-21", rating: "skated", grade: "B+" },
    last_clear_day: "2026-11-05" }, RUN), { text: "Skated yesterday (B+)", old: false });
  assert.deepEqual(evidenceLine({ last_clear_day: "2026-11-20",
    timeline: [{ day: "2026-11-20", kind: "image", text: "Crack network seen" }] }, RUN),
    { text: "Crack network seen Nov 20", old: false });
  assert.deepEqual(evidenceLine({ last_clear_day: "2026-11-05" }, RUN), { text: "Satellite Nov 5", old: true });
  assert.deepEqual(evidenceLine({}, RUN), { text: "No clear image yet", old: true });
});

const L = {
  a: { name: "A", label: "likely_black_ice", came_in: "2026-11-21", last_clear_day: "2026-11-20" },
  b: { name: "B", label: "likely_black_ice", came_in: "2026-11-22", last_clear_day: "2026-11-21",
       last_report: { day: "2026-11-10", rating: "skated", grade: "A+" } },
  c: { name: "C", label: "likely_black_ice", came_in: "2026-11-01", last_clear_day: "2026-11-19",
       last_report: { day: "2026-11-19", rating: "skated", grade: "B" } },
  d: { name: "D", label: "likely_black_ice", came_in: "2026-11-01" },
  e: { name: "E", label: "rough_ice", came_in: "2026-11-02", last_clear_day: "2026-11-12", pinned: true },
};
const P = { a: { area_acres: 100, road_mi: 4, trail_mi: 0 }, b: { area_acres: 50, road_mi: 0.1 },
  c: { area_acres: 3000, road_mi: 1.2, trail_mi: 0.5 }, d: { area_acres: 9000, road_mi: 9 }, e: { area_acres: 10 } };
const ids = (chip, skated = new Set()) => sortLakes(inLakes(L), chip, P, { runDate: RUN, skated }).map((l) => l.id);

test("sorts: pinned first, lakes with no evidence last", () => {
  assert.deepEqual(ids("just_in"), ["e", "b", "a", "c", "d"]);
  assert.deepEqual(ids("best_ice"), ["e", "b", "c", "a", "d"]);
  assert.deepEqual(ids("biggest"), ["e", "c", "a", "b", "d"]);
  assert.deepEqual(ids("new_to_you", new Set(["b"])), ["e", "a", "c", "b", "d"]);
  assert.deepEqual(ids("adventures"), ["e", "a", "c", "b", "d"]);
});

test("row text and dates", () => {
  assert.equal(shortDate("2026-11-05"), "Nov 5");
  assert.equal(skateMeta({ label: "likely_black_ice", last_clear_day: "2026-11-05", road_mi: 0.34 }, "Likely black ice"),
    "seen Nov 5 · 0.3 mi from road");
});

test("no acreage badge when the name already carries it", () => {
  const props = { u: { area_acres: 17.2, road_mi: 0.1 } };
  assert.deepEqual(badges({ id: "u", name: "Unnamed lake (17 ac)" }, props, { runDate: RUN, skated: null }), []);
  assert.deepEqual(badges({ id: "u", name: "Jean Lake" }, props, { runDate: RUN, skated: null }), ["17 ac"]);
});
