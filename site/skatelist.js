// Lakes worth listing as skateable today. ES module, tested in node.
const ORDER = { likely_black_ice: 0, rough_ice: 1 };

// Black ice first, then rough ice; within each: pinned, then the freshest clear
// satellite look (old evidence sinks), then nearest a road, then name. Hidden lakes
// are left out. `props` maps lake id -> {area_acres, road_mi}.
export function skateableLakes(lakes, props = {}) {
  return Object.entries(lakes)
    .filter(([, d]) => d.label in ORDER && !d.hidden)
    .map(([id, d]) => ({ id, ...d, road_mi: props[id]?.road_mi ?? null }))
    .sort((a, b) => ORDER[a.label] - ORDER[b.label]
      || Number(Boolean(b.pinned)) - Number(Boolean(a.pinned))
      || String(b.last_clear_day || "").localeCompare(String(a.last_clear_day || ""))
      || (a.road_mi ?? 1e9) - (b.road_mi ?? 1e9)
      || String(a.name).localeCompare(String(b.name)));
}

// "Nov 5" for "2026-11-05".
export function shortDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

// The line under a lake's name: thickness, when a satellite last saw it, road distance.
export function skateMeta(d, labelText) {
  const parts = [];
  if (d.thickness_cm != null) parts.push(`~${d.thickness_cm} cm`);
  if (d.label !== "likely_black_ice") parts.push(labelText);
  parts.push(d.last_clear_day ? `seen ${shortDate(d.last_clear_day)}` : "no clear image");
  if (d.road_mi != null) parts.push(d.road_mi < 0.1 ? "at the road" : `${d.road_mi.toFixed(1)} mi from road`);
  return parts.join(" · ");
}
