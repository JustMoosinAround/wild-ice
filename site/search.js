// Lake name search. ES module, no dependencies; usable from the page and node tests.
function fold(t) {
  return (t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

export function searchLakes(lakes, query, limit = 8) {
  const q = fold(query).trim();
  if (!q) return [];
  const hits = [];
  for (const [id, d] of Object.entries(lakes)) {
    const name = fold(d.name);
    const at = name.indexOf(q);
    if (at < 0) continue;
    const rank = at === 0 ? 0 : name[at - 1] === " " ? 1 : 2;
    hits.push({ id, rank, name: d.name, area: d.area_acres || 0 });
  }
  hits.sort((a, b) => a.rank - b.rank || b.area - a.area || a.name.localeCompare(b.name));
  return hits.slice(0, limit);
}
