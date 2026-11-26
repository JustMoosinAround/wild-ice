// Explore feed logic: which lakes are in, "Just in", badges, the evidence line and
// the five sorts. ES module, no DOM; tested in node (tests/js/explore.test.mjs).

export const CHIPS = [
  { id: "just_in", label: "Just in" },
  { id: "best_ice", label: "Best ice" },
  { id: "biggest", label: "Biggest" },
  { id: "new_to_you", label: "New to you" },
  { id: "trip_reports", label: "Trip reports" }, // a feed of what people skated, not a sort
];
export const JUST_IN_DAYS = 3;
const IN = new Set(["likely_black_ice", "rough_ice"]);
const SKATED = new Set(["skated", "rough"]);
const GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F+", "F", "F-"];
const OLD_DAYS = 7;

function days(a, b) { // b - a, ISO dates
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);
}

// "Nov 5" for "2026-11-05".
export function shortDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function inLakes(lakes) {
  return Object.entries(lakes).filter(([, d]) => IN.has(d.label) && !d.hidden).map(([id, d]) => ({ id, ...d }));
}

function skatedReport(d) {
  return d.last_report && SKATED.has(d.last_report.rating) ? d.last_report : null;
}

export function isJustIn(d, runDate) {
  if (!d.came_in || days(d.came_in, runDate) >= JUST_IN_DAYS) return false;
  const r = skatedReport(d);
  return !(r && r.day >= d.came_in);
}

export function isHikeIn(p) {
  return !!p && p.road_mi != null && p.road_mi > 0.5 && p.trail_mi != null && p.trail_mi <= 1;
}

export function badges(d, props, ctx) {
  const p = props[d.id] || {};
  const out = [];
  if (isJustIn(d, ctx.runDate)) out.push("Just in · no tracks yet");
  const r = skatedReport(d);
  if (r && r.grade) out.push(`Last grade ${r.grade}`);
  // Unnamed lakes already say "(17 ac)" in their name.
  if (p.area_acres != null && !/\(\d[\d,]* ac\)$/.test(d.name || "")) out.push(`${Math.round(p.area_acres).toLocaleString("en-US")} ac`);
  if (ctx.skated && !ctx.skated.has(d.id)) out.push("New to you");
  if (isHikeIn(p)) out.push(`Approach ~${p.road_mi.toFixed(1)} mi`);
  return out;
}

// The freshest piece of evidence: a skated report, a crack network, or a clear image.
function evidence(d) {
  const ev = [];
  const r = skatedReport(d);
  if (r) ev.push({ day: r.day, rank: 0, r });
  const crack = (d.timeline || []).find((e) => e.kind === "image" && e.text === "Crack network seen");
  if (crack) ev.push({ day: crack.day, rank: 1 });
  if (d.last_clear_day) ev.push({ day: d.last_clear_day, rank: 2 });
  ev.sort((a, b) => b.day.localeCompare(a.day) || a.rank - b.rank);
  return ev[0] || null;
}

function when(day, runDate) {
  const n = days(day, runDate);
  return n === 0 ? "today" : n === 1 ? "yesterday" : shortDate(day);
}

export function evidenceLine(d, runDate) {
  const e = evidence(d);
  if (!e) return { text: "No clear image yet", old: true };
  const old = days(e.day, runDate) > OLD_DAYS;
  if (e.rank === 0) return { text: `Skated ${when(e.day, runDate)}${e.r.grade ? ` (${e.r.grade})` : ""}`, old };
  if (e.rank === 1) return { text: `Crack network seen ${shortDate(e.day)}`, old };
  return { text: `Satellite ${shortDate(e.day)}`, old };
}

export function sortLakes(list, chip, props, ctx) {
  const fresh = (d) => evidence(d)?.day || "";
  const grade = (d) => { const r = skatedReport(d); const i = r && r.grade ? GRADES.indexOf(r.grade) : -1; return i < 0 ? 99 : i; };
  const area = (d) => props[d.id]?.area_acres || 0;
  const justIn = (d) => isJustIn(d, ctx.runDate);
  const byJustIn = (a, b) => Number(justIn(b)) - Number(justIn(a))
    || (justIn(a) && justIn(b) ? String(b.came_in).localeCompare(String(a.came_in)) : 0)
    || fresh(b).localeCompare(fresh(a));
  const key = {
    just_in: byJustIn,
    best_ice: (a, b) => grade(a) - grade(b) || fresh(b).localeCompare(fresh(a)),
    biggest: (a, b) => area(b) - area(a),
    new_to_you: (a, b) => (ctx.skated ? Number(ctx.skated.has(a.id)) - Number(ctx.skated.has(b.id)) : 0) || byJustIn(a, b),
  }[chip] || byJustIn;
  return [...list].sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned))
    || Number(!evidence(a)) - Number(!evidence(b))
    || key(a, b)
    || String(a.name).localeCompare(String(b.name)));
}

// One-line summary used by the simple list (when last seen, road distance).
export function skateMeta(d, labelText) {
  const parts = [];
  if (d.label !== "likely_black_ice") parts.push(labelText);
  parts.push(d.last_clear_day ? `seen ${shortDate(d.last_clear_day)}` : "no clear image");
  if (d.road_mi != null) parts.push(d.road_mi < 0.1 ? "at the road" : `${d.road_mi.toFixed(1)} mi from road`);
  return parts.join(" · ");
}
