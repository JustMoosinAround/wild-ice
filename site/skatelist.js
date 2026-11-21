// Lakes worth listing as skateable today. ES module, tested in node.
const ORDER = { likely_black_ice: 0, rough_ice: 1 };

// Black ice first (pinned, then thicker ice, then bigger lakes), then rough ice;
// hidden lakes are left out. `areas` maps lake id -> acres.
export function skateableLakes(lakes, areas = {}) {
  return Object.entries(lakes)
    .filter(([, d]) => d.label in ORDER && !d.hidden)
    .map(([id, d]) => ({ id, ...d, area: areas[id] || 0 }))
    .sort((a, b) => ORDER[a.label] - ORDER[b.label]
      || Number(Boolean(b.pinned)) - Number(Boolean(a.pinned))
      || (b.thickness_cm || 0) - (a.thickness_cm || 0)
      || b.area - a.area
      || String(a.name).localeCompare(String(b.name)));
}
