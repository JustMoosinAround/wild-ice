import { test } from "node:test";
import assert from "node:assert/strict";
import { activeCount, clean, defaults, miles, passes, SKATE } from "../../site/mapfilter.js";

const p = (o = {}) => ({ area_acres: 30, road_mi: 0.1, trail_mi: 0, lat: 61.2, lon: -149.9, ...o });
const d = (o = {}) => ({ label: "likely_black_ice", ...o });

test("defaults show every lake and count as no filter", () => {
  const f = defaults();
  assert.equal(activeCount(f), 0);
  for (const label of ["open_water", "snow_covered", "unknown"]) assert.ok(passes(f, p(), d({ label })));
});

test("conditions, size, access, just in", () => {
  const f = { ...defaults(), labels: SKATE };
  assert.ok(passes(f, p(), d()));
  assert.ok(!passes(f, p(), d({ label: "snow_covered" })));
  assert.ok(!passes({ ...defaults(), minAcres: 50 }, p(), d()));
  assert.ok(passes({ ...defaults(), minAcres: 10 }, p(), d()));
  assert.ok(passes({ ...defaults(), access: "road" }, p(), d()));
  assert.ok(!passes({ ...defaults(), access: "road" }, p({ road_mi: 3 }), d()));
  assert.ok(passes({ ...defaults(), access: "approach" }, p({ road_mi: 3, trail_mi: 0.2 }), d()));
  assert.ok(!passes({ ...defaults(), access: "approach" }, p(), d()));
  const ji = { ...defaults(), justIn: true };
  assert.ok(passes(ji, p(), d({ came_in: "2026-11-21" }), { runDate: "2026-11-22" }));
  assert.ok(!passes(ji, p(), d({ came_in: "2026-11-01" }), { runDate: "2026-11-22" }));
  assert.equal(activeCount({ ...defaults(), labels: SKATE, minAcres: 50, justIn: true }), 3);
});

test("distance from me only applies once we know where you are", () => {
  const f = { ...defaults(), maxMiles: 25 };
  assert.ok(passes(f, p(), d()));                                   // no location yet: no cut
  assert.ok(passes(f, p(), d(), { here: { lat: 61.3, lon: -149.9 } }));
  assert.ok(!passes(f, p(), d(), { here: { lat: 64.8, lon: -147.7 } })); // Fairbanks
  assert.ok(Math.abs(miles(61.2, -149.9, 61.2, -149.9)) < 1e-9);
});

test("clean drops junk from storage", () => {
  assert.deepEqual(clean(null), defaults());
  assert.deepEqual(clean({ labels: ["freezing", "bogus"], minAcres: 7, access: "x", maxMiles: 25, justIn: "yes" }),
    { labels: ["freezing"], minAcres: 0, access: "any", maxMiles: 25, justIn: false });
});
