import { test } from "node:test";
import assert from "node:assert/strict";
import { searchLakes } from "../../site/search.js";

const LAKES = {
  a: { name: "Bonnie Lake", area_acres: 60 },
  b: { name: "Upper Bonnie Lake", area_acres: 40 },
  c: { name: "Lake Bonnie View", area_acres: 500 },
  d: { name: "Ravine Lake", area_acres: 12 },
  e: { name: "Lake Louise", area_acres: 14000 },
  f: { name: "Little Lake Louise", area_acres: 1200 },
  g: { name: null },
};

test("name start ranks first, then word start, then larger lakes", () => {
  assert.deepEqual(searchLakes(LAKES, "bonnie").map((h) => h.id), ["a", "c", "b"]);
});

test("case and accents are ignored; empty query finds nothing", () => {
  assert.deepEqual(searchLakes(LAKES, "  RAVÍNE ").map((h) => h.id), ["d"]);
  assert.deepEqual(searchLakes(LAKES, "   "), []);
});

test("substring inside a word still matches, bigger lake first among equals", () => {
  assert.deepEqual(searchLakes(LAKES, "ouise").map((h) => h.id), ["e", "f"]);
});

test("limit caps the list and unnamed lakes never match", () => {
  assert.equal(searchLakes(LAKES, "lake", 2).length, 2);
  assert.ok(!searchLakes(LAKES, "null").length);
});
