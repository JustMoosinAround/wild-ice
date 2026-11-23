// Map filter: which lakes show on the map. Pure functions so tests can check them.
import { isHikeIn, isJustIn } from "./explore.js";

export const LABELS = ["likely_black_ice", "rough_ice", "freezing", "unknown", "snow_covered", "open_water"];
export const SKATE = ["likely_black_ice", "rough_ice", "freezing"];

export const SIZES = [[0, "Any"], [10, "10+ ac"], [50, "50+ ac"], [250, "250+ ac"], [1000, "1,000+ ac"]];
export const DISTANCES = [[0, "Any"], [10, "10 mi"], [25, "25 mi"], [50, "50 mi"], [100, "100 mi"]];
export const ACCESS = [["any", "Any"], ["road", "By the road"], ["approach", "Approach (hike in)"]];

export function defaults() {
  return { labels: [...LABELS], minAcres: 0, access: "any", maxMiles: 0, justIn: false };
}

// A stored or hand-made filter, with anything unknown replaced by the default.
export function clean(f) {
  const d = defaults();
  if (!f || typeof f !== "object") return d;
  const labels = Array.isArray(f.labels) ? f.labels.filter((l) => LABELS.includes(l)) : d.labels;
  return {
    labels,
    minAcres: SIZES.some(([v]) => v === f.minAcres) ? f.minAcres : 0,
    access: ACCESS.some(([v]) => v === f.access) ? f.access : "any",
    maxMiles: DISTANCES.some(([v]) => v === f.maxMiles) ? f.maxMiles : 0,
    justIn: f.justIn === true,
  };
}

// How many settings differ from "show everything" (for the badge on the button).
export function activeCount(f) {
  return (f.labels.length < LABELS.length ? 1 : 0) + (f.minAcres ? 1 : 0)
    + (f.access !== "any" ? 1 : 0) + (f.maxMiles ? 1 : 0) + (f.justIn ? 1 : 0);
}

export function miles(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const h = Math.sin((lat2 - lat1) * r / 2) ** 2
    + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
  return 2 * 3958.8 * Math.asin(Math.sqrt(h));
}

// f: filter; p: lake properties (area_acres, road_mi, trail_mi, lat, lon);
// d: the lake's status entry (label, came_in, last_report); ctx: {runDate, here: {lat, lon} | null}
export function passes(f, p, d, ctx = {}) {
  if (!d) return f.labels.length === LABELS.length && !f.justIn;
  if (!f.labels.includes(d.label)) return false;
  if (f.minAcres && !(p && p.area_acres >= f.minAcres)) return false;
  if (f.access === "road" && !(p && p.road_mi != null && p.road_mi <= 0.5)) return false;
  if (f.access === "approach" && !isHikeIn(p)) return false;
  if (f.maxMiles && ctx.here && p && p.lat != null
    && miles(ctx.here.lat, ctx.here.lon, p.lat, p.lon) > f.maxMiles) return false;
  if (f.justIn && !isJustIn(d, ctx.runDate)) return false;
  return true;
}
