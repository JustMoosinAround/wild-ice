// Member-added spots: marshes, rivers, sloughs and ponds that aren't catalog lakes.
// Made from an uploaded track (its box and middle point); their state is members' reports.
import { requireDevice, requireOwner } from "./auth.js";
import { HttpError, json, now, readJson } from "./http.js";

const KINDS = ["marsh", "river", "slough", "pond", "other"];
const PER_DAY = 10;
const NEAR_DEG = 0.004;     // ~400 m: a new track this close to a spot's box is that spot
const MAX_SPAN_DEG = 0.25;  // a track box bigger than ~25 km isn't one spot
const RECENT_DAYS = 14;     // reports older than this don't colour a spot
const LINK = /https?:\/\/|www\.|\.[a-z]{2,}\//i;

function num(v) { return typeof v === "number" && Number.isFinite(v); }

export async function postSpot(env, request) {
  const who = await requireDevice(env, request);
  const b = await readJson(request);
  const name = typeof b.name === "string" ? b.name.trim().replace(/\s+/g, " ") : "";
  if (!name || name.length > 60) throw new HttpError(400, "Give it a name (up to 60 characters)");
  if (LINK.test(name)) throw new HttpError(400, "No links in names");
  if (!KINDS.includes(b.kind)) throw new HttpError(400, "Pick what kind of place it is");
  const [w, s, e, n] = Array.isArray(b.bbox) ? b.bbox : [];
  if (![w, s, e, n, b.lat, b.lon].every(num) || w > e || s > n || e - w > MAX_SPAN_DEG || n - s > MAX_SPAN_DEG
      || b.lat < s - NEAR_DEG || b.lat > n + NEAR_DEG || b.lon < w - 2 * NEAR_DEG || b.lon > e + 2 * NEAR_DEG
      || Math.abs(b.lat) > 90 || Math.abs(b.lon) > 180) throw new HttpError(400, "Bad track box");
  // Already here? Then it's that spot (so a marsh isn't added twice).
  const near = await env.DB.prepare(
    `SELECT id, name, kind FROM spots WHERE hidden = 0 AND ? BETWEEN min_lat - ? AND max_lat + ?
     AND ? BETWEEN min_lon - ? AND max_lon + ? LIMIT 1`,
  ).bind(b.lat, NEAR_DEG, NEAR_DEG, b.lon, 2 * NEAR_DEG, 2 * NEAR_DEG).first();
  if (near) return json({ ...near, existing: true });
  const since = new Date(Date.now() - 86400e3).toISOString();
  const count = await env.DB.prepare("SELECT COUNT(*) AS n FROM spots WHERE friend_id = ? AND created_at > ?")
    .bind(who.id, since).first("n");
  if (count >= PER_DAY) throw new HttpError(429, "That's a lot of new spots today, try again tomorrow");
  const id = "s" + [...crypto.getRandomValues(new Uint8Array(6))].map((x) => x.toString(16).padStart(2, "0")).join("");
  await env.DB.prepare(
    `INSERT INTO spots (id, name, kind, lat, lon, min_lon, min_lat, max_lon, max_lat, friend_id, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind(id, name, b.kind, b.lat, b.lon, w, s, e, n, who.id, now()).run();
  return json({ id, name, kind: b.kind, existing: false });
}

// Every spot with its newest recent report (what colours it on the map).
export async function getSpots(env) {
  const since = new Date(Date.now() - RECENT_DAYS * 86400_000).toISOString().slice(0, 10);
  const { results } = await env.DB.prepare(
    `SELECT s.id, s.name, s.kind, s.lat, s.lon, s.min_lon, s.min_lat, s.max_lon, s.max_lat, s.created_at,
            f.name AS added_by,
            (SELECT r.rating || '|' || COALESCE(r.grade, '') || '|' || r.day FROM reports r
              WHERE r.lake_id = s.id AND r.day >= ? ORDER BY r.day DESC, r.created_at DESC LIMIT 1) AS last
     FROM spots s LEFT JOIN friends f ON f.id = s.friend_id WHERE s.hidden = 0`,
  ).bind(since).all();
  return json({ spots: results.map(({ last, min_lon, min_lat, max_lon, max_lat, ...sp }) => {
    const [rating, grade, day] = last ? last.split("|") : [];
    return { ...sp, bbox: [min_lon, min_lat, max_lon, max_lat],
      last_report: last ? { rating, grade: grade || null, day } : null };
  }) });
}

// Owner: hide a spot (spam or a duplicate).
export async function hideSpot(env, request, id) {
  await requireOwner(env, request);
  const r = await env.DB.prepare("UPDATE spots SET hidden = 1 WHERE id = ?").bind(id).run();
  if (r.meta.changes !== 1) throw new HttpError(404, "No such spot");
  return json({ ok: true });
}
