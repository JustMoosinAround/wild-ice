import { test } from "node:test";
import assert from "node:assert/strict";
import { GLOSSARY } from "../../site/glossary.js";

const terms = GLOSSARY.flatMap((s) => s.items.map((i) => i.term));

test("every hazard chip, badge, sort and map colour has an entry", () => {
  for (const t of ["New ice", "Big ice", "Lead risk", "Thaw-weakened", "Rotten ice risk", "Slush", "Pressure ridges",
    "Just in", "Approach", "New to you", "Grade", "Likely skateable", "Dark image", "Skateable, rough", "Freezing", "Unknown",
    "Snow covered", "Open water", "Crack network", "Freeze-up"]) {
    assert.ok(terms.includes(t), `missing ${t}`);
  }
  for (const s of GLOSSARY) for (const i of s.items) assert.ok(i.text.length > 10, i.term);
});
