import { test } from "node:test";
import assert from "node:assert/strict";
import { chartMarkers } from "../../site/chart.js";

test("graph markers: clear images and reports, coloured by what was seen", () => {
  const m = chartMarkers([
    { day: "2026-11-21", kind: "report", text: "Skated (B+)" },
    { day: "2026-11-20", kind: "image", text: "Crack network seen" },
    { day: "2026-11-18", kind: "snow", text: "8 cm new snow at Willow" },
    { day: "2026-11-12", kind: "image", text: "White (snow) on image" },
    { day: "2026-11-10", kind: "reset", text: "Froze up" },
  ]);
  assert.deepEqual(m.map((x) => [x.day, x.cls]), [
    ["2026-11-21", "mk-report"], ["2026-11-20", "mk-crack"], ["2026-11-12", "mk-white"], ["2026-11-10", "mk-reset"]]);
  assert.equal(m[0].text, "Skated (B+)");
  assert.deepEqual(chartMarkers(undefined), []);
});
