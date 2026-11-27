import { test } from "node:test";
import assert from "node:assert/strict";
import { bigIce, comingIn, nearest, outlinePath, seasonCounts } from "../../site/explore.js";

const lakes = {
  a: { name: "A", label: "freezing", thickness_cm: 3 }, b: { name: "B", label: "freezing", thickness_cm: 4.5 },
  c: { name: "C", label: "likely_black_ice" }, d: { name: "D", label: "open_water" }, e: { name: "E", label: "snow_covered", hidden: true },
};
const props = { a: { lat: 61.2, lon: -149.9, area_acres: 40 }, b: { lat: 61.6, lon: -149.4, area_acres: 900 },
  c: { lat: 61.21, lon: -149.88, area_acres: 25 }, d: { lat: 61.2, lon: -149.9, area_acres: 5000 } };

test("home sections", () => {
  assert.deepEqual(seasonCounts(lakes), { likely_black_ice: 1, rough_ice: 0, freezing: 2, unknown: 0, snow_covered: 0, open_water: 1 });
  assert.deepEqual(comingIn(lakes).map((x) => x.id), ["b", "a"]);
  assert.deepEqual(nearest(lakes, props, { lat: 61.2, lon: -149.9 }).map((x) => x.id), ["a", "c", "b"]); // no open water
  assert.deepEqual(bigIce(lakes, props).map((x) => x.id), ["b", "a", "c"]);
});

test("lake outline fits its box", () => {
  const sq = { type: "Polygon", coordinates: [[[-150, 61], [-149.99, 61], [-149.99, 61.01], [-150, 61.01], [-150, 61]]] };
  const d = outlinePath(sq, 160, 90, 8);
  assert.match(d, /^M[\d.]+,[\d.]+L/);
  for (const [x, y] of d.slice(1, -1).split("L").map((p) => p.split(",").map(Number))) { assert.ok(x >= 8 && x <= 152); assert.ok(y >= 8 && y <= 82); }
  assert.equal(outlinePath(null), "");
});
