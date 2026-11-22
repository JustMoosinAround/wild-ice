import { test } from "node:test";
import assert from "node:assert/strict";
import { skateableLakes, skateMeta } from "../../site/skatelist.js";

const lakes = {
  a: { name: "Cheney Lake", label: "likely_black_ice", last_clear_day: "2026-11-02", pinned: true },
  b: { name: "University Lake", label: "likely_black_ice", last_clear_day: "2026-11-20" },
  c: { name: "Big Lake", label: "likely_black_ice", last_clear_day: "2026-11-20" },
  g: { name: "Old Lake", label: "likely_black_ice", last_clear_day: "2026-10-27" },
  d: { name: "Rough One", label: "rough_ice", last_clear_day: "2026-11-21" },
  e: { name: "Frozen-ish", label: "freezing" },
  f: { name: "Hidden Lake", label: "likely_black_ice", hidden: true },
};
const props = { a: { road_mi: 0.1 }, b: { road_mi: 0.5 }, c: { road_mi: 0.2 }, g: { road_mi: 0 } };

test("pinned, then freshest look, then nearest road; rough ice last; hidden and others out", () => {
  assert.deepEqual(skateableLakes(lakes, props).map((l) => l.id), ["a", "c", "b", "g", "d"]);
});

test("empty when nothing is skateable", () => {
  assert.deepEqual(skateableLakes({ e: lakes.e }, {}), []);
});

test("row text: thickness, when last seen, road distance; no confidence", () => {
  assert.equal(skateMeta({ label: "likely_black_ice", thickness_cm: 22, last_clear_day: "2026-11-05", road_mi: 0.34 }, "Likely black ice"),
    "~22 cm · seen Nov 5 · 0.3 mi from road");
  assert.equal(skateMeta({ label: "rough_ice", thickness_cm: 30, road_mi: 0 }, "Skateable, rough"),
    "~30 cm · Skateable, rough · no clear image · at the road");
});
