// Read an uploaded GPX / FIT (.gz) track on the phone and find which catalog lakes it
// skated, with the same rules as wildice/skatelog.py. The track never leaves the phone.
// ES module, no DOM; tested in node (tests/js/track.test.mjs).

export class TrackError extends Error {}

const MIN_MINUTES = 10;
const MIN_SHARE = 0.3;
const MAX_GAP_S = 300;
const SHORE_SLACK_M = 60;
const FIT_EPOCH_S = 631065600; // 1989-12-31T00:00:00Z
const SEMI = 180 / 2 ** 31;

export function parseGpx(text) {
  const out = [];
  let timed = 0;
  const re = /<trkpt\b([^>]*?)(?:\/>|>([\s\S]*?)<\/trkpt>)/g;
  for (let m; (m = re.exec(text));) {
    const lat = Number(/\blat="([^"]+)"/.exec(m[1])?.[1]);
    const lon = Number(/\blon="([^"]+)"/.exec(m[1])?.[1]);
    const time = /<time>([^<]+)<\/time>/.exec(m[2] || "")?.[1];
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    const t = time ? Date.parse(time) : NaN;
    if (Number.isFinite(t)) timed++;
    out.push({ lat, lon, t });
  }
  if (!out.length) throw new TrackError("No track points in this file");
  if (!timed) throw new TrackError("This track has no times");
  return out.filter((p) => Number.isFinite(p.t));
}

export function parseFit(buf) {
  const v = new DataView(buf);
  if (v.byteLength < 14) throw new TrackError("Couldn't read this file");
  const hsize = v.getUint8(0);
  const magic = String.fromCharCode(v.getUint8(8), v.getUint8(9), v.getUint8(10), v.getUint8(11));
  if (magic !== ".FIT") throw new TrackError("Couldn't read this file");
  const end = Math.min(v.byteLength, hsize + v.getUint32(4, true));
  const defs = {};
  const out = [];
  let o = hsize, lastTs = null;
  while (o < end) {
    const h = v.getUint8(o++);
    if (h & 0x80) { // compressed-timestamp data message
      const def = defs[(h >> 5) & 3];
      if (!def) throw new TrackError("Couldn't read this file");
      const off = h & 0x1f;
      if (lastTs != null) lastTs = (lastTs & ~0x1f) + off + (off >= (lastTs & 0x1f) ? 0 : 0x20);
      o = readData(v, o, def, out, lastTs, (t) => { lastTs = t; });
      continue;
    }
    const local = h & 0x0f;
    if (h & 0x40) { // definition
      const little = v.getUint8(o + 1) === 0;
      const global = v.getUint16(o + 2, little);
      const n = v.getUint8(o + 4);
      o += 5;
      const fields = [];
      for (let i = 0; i < n; i++, o += 3) fields.push({ num: v.getUint8(o), size: v.getUint8(o + 1) });
      if (h & 0x20) { const dn = v.getUint8(o); o += 1; for (let i = 0; i < dn; i++, o += 3) fields.push({ num: -1, size: v.getUint8(o + 1) }); }
      defs[local] = { global, little, fields };
    } else {
      const def = defs[local];
      if (!def) throw new TrackError("Couldn't read this file");
      o = readData(v, o, def, out, null, (t) => { lastTs = t; });
    }
  }
  return out;
}

function readData(v, o, def, out, ts, setTs) {
  let lat = null, lon = null, t = ts;
  for (const f of def.fields) {
    if (def.global === 20 && f.size === 4) {
      if (f.num === 0) { const x = v.getInt32(o, def.little); if (x !== 0x7fffffff) lat = x * SEMI; }
      if (f.num === 1) { const x = v.getInt32(o, def.little); if (x !== 0x7fffffff) lon = x * SEMI; }
    }
    if (f.num === 253 && f.size === 4) { t = v.getUint32(o, def.little); setTs(t); }
    o += f.size;
  }
  if (def.global === 20 && lat != null && lon != null && t != null) out.push({ lat, lon, t: (t + FIT_EPOCH_S) * 1000 });
  return o;
}

async function gunzip(bytes) {
  try {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    return await new Response(stream).arrayBuffer();
  } catch {
    throw new TrackError("Couldn't read this file");
  }
}

export async function readTrackFile(file) {
  let name = file.name.toLowerCase();
  let buf = await file.arrayBuffer();
  if (name.endsWith(".gz")) { buf = await gunzip(buf); name = name.slice(0, -3); }
  try {
    if (name.endsWith(".gpx")) return parseGpx(new TextDecoder().decode(buf));
    if (name.endsWith(".fit")) return parseFit(buf);
  } catch (e) {
    throw e instanceof TrackError ? e : new TrackError("Couldn't read this file");
  }
  throw new TrackError("Pick a .gpx, .fit or .fit.gz file");
}

// --- geometry (small lakes, so a local flat projection is fine) ---------------------

function rings(geom) {
  if (!geom) return [];
  if (geom.type === "Polygon") return [geom.coordinates];
  if (geom.type === "MultiPolygon") return geom.coordinates;
  return [];
}

function inRing(ring, x, y) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function segDistM(lat, lon, a, b) {
  const k = 111320 * Math.cos((lat * Math.PI) / 180);
  const ax = (a[0] - lon) * k, ay = (a[1] - lat) * 110540, bx = (b[0] - lon) * k, by = (b[1] - lat) * 110540;
  const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / l2)) : 0;
  return Math.hypot(ax + t * dx, ay + t * dy);
}

function inPolys(polys, lat, lon) {
  return polys.some((poly) => inRing(poly[0], lon, lat) && !poly.slice(1).some((h) => inRing(h, lon, lat)));
}

const CELL_LAT = 0.001, CELL_LON = 0.002; // ~110 m cells at 61 N
const SLACK_LAT = SHORE_SLACK_M / 110540;

// A per-lake lookup that answers "is this point on the lake (or within SHORE_SLACK_M
// of it)?" quickly: shoreline segments are bucketed into ~110 m cells, and cells with
// no shoreline nearby take one cached inside/outside answer.
function lakeIndex(polys, box) {
  const slackLon = SHORE_SLACK_M / (111320 * Math.cos((box[1] * Math.PI) / 180));
  const segs = new Map();
  const key = (i, j) => i * 1e6 + j;
  for (const poly of polys) for (const ring of poly) for (let k = 1; k < ring.length; k++) {
    const a = ring[k - 1], b = ring[k];
    const i0 = Math.floor((Math.min(a[1], b[1]) - SLACK_LAT) / CELL_LAT), i1 = Math.floor((Math.max(a[1], b[1]) + SLACK_LAT) / CELL_LAT);
    const j0 = Math.floor((Math.min(a[0], b[0]) - slackLon) / CELL_LON), j1 = Math.floor((Math.max(a[0], b[0]) + slackLon) / CELL_LON);
    for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) {
      const kk = key(i, j);
      if (!segs.has(kk)) segs.set(kk, []);
      segs.get(kk).push([a, b]);
    }
  }
  const cellInside = new Map();
  return (lat, lon) => {
    if (lon < box[0] || lon > box[2] || lat < box[1] || lat > box[3]) return false;
    const i = Math.floor(lat / CELL_LAT), j = Math.floor(lon / CELL_LON), kk = key(i, j);
    const near = segs.get(kk);
    if (!near) {
      if (!cellInside.has(kk)) cellInside.set(kk, inPolys(polys, (i + 0.5) * CELL_LAT, (j + 0.5) * CELL_LON));
      return cellInside.get(kk);
    }
    for (const [a, b] of near) if (segDistM(lat, lon, a, b) <= SHORE_SLACK_M) return true;
    return inPolys(polys, lat, lon);
  };
}

function bbox(polys) {
  let a = [Infinity, Infinity, -Infinity, -Infinity];
  for (const p of polys) for (const [x, y] of p[0]) a = [Math.min(a[0], x), Math.min(a[1], y), Math.max(a[2], x), Math.max(a[3], y)];
  const pad = 0.002;
  return [a[0] - pad, a[1] - pad, a[2] + pad, a[3] + pad];
}

export function alaskaDay(ms) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Anchorage", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(ms));
}

export function matchLakes(points, features) {
  if (points.length < 2) return [];
  const gaps = points.slice(1).map((p, i) => { const s = (p.t - points[i].t) / 1000; return s > 0 && s <= MAX_GAP_S ? s : 0; });
  const total = gaps.reduce((a, b) => a + b, 0);
  if (total <= 0) return [];
  const tb = [Infinity, Infinity, -Infinity, -Infinity]; // a loop: spreading 100k+ points overflows the stack
  for (const p of points) {
    if (p.lon < tb[0]) tb[0] = p.lon; if (p.lat < tb[1]) tb[1] = p.lat;
    if (p.lon > tb[2]) tb[2] = p.lon; if (p.lat > tb[3]) tb[3] = p.lat;
  }
  const out = [];
  for (const f of features) {
    const polys = rings(f.geometry);
    if (!polys.length) continue;
    const b = bbox(polys);
    if (b[0] > tb[2] || b[2] < tb[0] || b[1] > tb[3] || b[3] < tb[1]) continue;
    const on = lakeIndex(polys, b);
    const inside = points.map((p) => on(p.lat, p.lon));
    let secs = 0;
    const onIdx = [];
    gaps.forEach((g, i) => { if (g && inside[i] && inside[i + 1]) { secs += g; onIdx.push(i); } });
    const minutes = secs / 60, share = secs / total;
    if (minutes < MIN_MINUTES || share < MIN_SHARE) continue;
    const mid = points[onIdx[Math.floor(onIdx.length / 2)]];
    out.push({ lakeId: f.properties.id, name: f.properties.name, minutes: Math.round(minutes),
      share: Math.round(share * 1000) / 1000, day: alaskaDay(mid.t), point: { lat: mid.lat, lon: mid.lon } });
  }
  return out.sort((a, b) => b.minutes - a.minutes);
}
