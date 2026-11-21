import { test } from "node:test";
import assert from "node:assert/strict";
import { skateableLakes } from "../../site/skatelist.js";

const lakes = {
  a: { name: "Cheney Lake", label: "likely_black_ice", thickness_cm: 10, pinned: true },
  b: { name: "University Lake", label: "likely_black_ice", thickness_cm: 14 },
  c: { name: "Big Lake", label: "likely_black_ice", thickness_cm: 14 },
  d: { name: "Rough One", label: "rough_ice", thickness_cm: 20 },
  e: { name: "Frozen-ish", label: "freezing", thickness_cm: 5 },
  f: { name: "Hidden Lake", label: "likely_black_ice", thickness_cm: 30, hidden: true },
};
const area = { a: 25, b: 40, c: 3000, d: 100 };

test("black ice first (pinned, then thicker, then bigger), then rough; hidden and others left out", () => {
  assert.deepEqual(skateableLakes(lakes, area).map((l) => l.id), ["a", "c", "b", "d"]);
});

test("empty when nothing is skateable", () => {
  assert.deepEqual(skateableLakes({ e: lakes.e }, {}), []);
});
