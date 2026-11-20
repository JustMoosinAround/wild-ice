// On-the-ice reports (with an optional, already resized and metadata-free photo).
import { deviceFriend, newToken, requireDevice, requireService } from "./auth.js";
import { HttpError, json, now, readJson } from "./http.js";

export const RATINGS = ["skated", "snow", "water", "rough"];
export const GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-",
  "D+", "D", "D-", "F+", "F", "F-"];
const GRADED = new Set(["skated", "rough"]);
const MAX_PHOTO_BYTES = 1.5 * 1024 * 1024;
const MAX_NOTE = 300;
const MAX_AGE_DAYS = 14;

export function alaskaDay(date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Anchorage", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(date);
}

function daysBetween(a, b) {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);
}

function bad(message) {
  throw new HttpError(400, message);
}

function decodePhoto(b64) {
  if (typeof b64 !== "string" || !b64) bad("Photo must be a JPEG");
  // Size check before decoding: base64 is 4 chars per 3 bytes.
  if ((b64.length * 3) / 4 > MAX_PHOTO_BYTES + 3) throw new HttpError(413, "Photo too large");
  let bin;
  try { bin = atob(b64); } catch { bad("Photo must be a JPEG"); }
  if (bin.length > MAX_PHOTO_BYTES) throw new HttpError(413, "Photo too large");
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8 || bytes[2] !== 0xff) bad("Photo must be a JPEG");
  return bytes;
}

export function validateReport(body, today = alaskaDay()) {
  const idem = body.idem_key;
  if (typeof idem !== "string" || idem.length < 8 || idem.length > 64) bad("Missing idem_key");
  if (typeof body.lake_id !== "string" || !/^[wr]\d{1,12}$/.test(body.lake_id)) bad("Unknown lake");
  if (!RATINGS.includes(body.rating)) bad("Pick a condition");
  let grade = body.grade ?? null;
  if (grade !== null) {
    if (!GRADED.has(body.rating)) bad("Grades go with Skateable or Rough ice");
    if (!GRADES.includes(grade)) bad("Unknown grade");
  }
  const note = body.note == null ? "" : String(body.note).trim();
  if (note.length > MAX_NOTE) bad(`Note is over ${MAX_NOTE} characters`);
  const day = body.day == null ? today : body.day;
  if (typeof day !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(day) || Number.isNaN(Date.parse(day))) bad("Bad day");
  const age = daysBetween(day, today);
  if (age < 0) bad("That day hasn't happened yet");
  if (age > MAX_AGE_DAYS) bad(`Reports must be from the last ${MAX_AGE_DAYS} days`);
  let gps = null;
  if (body.gps != null) {
    const { lat, lon, source } = body.gps;
    if (typeof lat !== "number" || typeof lon !== "number" || !Number.isFinite(lat) || !Number.isFinite(lon)
        || lat < -90 || lat > 90 || lon < -180 || lon > 180) bad("Bad location");
    if (source !== "photo" && source !== "device") bad("Bad location source");
    gps = { lat, lon, source };
  }
  const photo = body.photo == null ? null : decodePhoto(body.photo);
  return { idem, lake_id: body.lake_id, rating: body.rating, grade, note, day, gps, photo };
}

export async function postReport(env, request) {
  const who = await requireDevice(env, request);
  const r = validateReport(await readJson(request));
  const existing = await env.DB.prepare(
    "SELECT id, friend_id FROM reports WHERE idem_key = ?").bind(r.idem).first();
  if (existing) {
    if (existing.friend_id !== who.id) throw new HttpError(409, "Duplicate key");
    return json({ id: existing.id });
  }
  const id = crypto.randomUUID();
  let photoId = null;
  if (r.photo) {
    photoId = crypto.randomUUID();
    const publicId = newToken();
    await env.PHOTOS.put(`photo:${publicId}`, r.photo);
    await env.DB.prepare(
      `INSERT INTO photos (id, public_id, lake_id, friend_id, created_at, status)
       VALUES (?, ?, ?, ?, ?, 'pending')`,
    ).bind(photoId, publicId, r.lake_id, who.id, now()).run();
  }
  try {
    await env.DB.prepare(
      `INSERT INTO reports (id, idem_key, friend_id, lake_id, day, created_at, rating, grade, note,
                            lat, lon, gps_source, photo_id)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(id, r.idem, who.id, r.lake_id, r.day, now(), r.rating, r.grade, r.note,
      r.gps?.lat ?? null, r.gps?.lon ?? null, r.gps?.source ?? null, photoId).run();
  } catch (err) {
    // A simultaneous resend won the UNIQUE(idem_key) race: answer with its id.
    const row = await env.DB.prepare("SELECT id FROM reports WHERE idem_key = ?").bind(r.idem).first();
    if (!row) throw err;
    return json({ id: row.id });
  }
  return json({ id });
}

export async function getPhoto(env, request, publicId) {
  const p = await env.DB.prepare("SELECT status FROM photos WHERE public_id = ?").bind(publicId).first();
  let allowed = p && p.status === "featured";
  if (p && !allowed && p.status === "pending") {
    const who = await deviceFriend(env, request);
    allowed = who?.role === "owner";
  }
  const bytes = allowed ? await env.PHOTOS.get(`photo:${publicId}`, "arrayBuffer") : null;
  if (!bytes) throw new HttpError(404, "No such photo");
  return new Response(bytes, {
    headers: { "Content-Type": "image/jpeg", "Cache-Control": p.status === "featured" ? "public, max-age=86400" : "private, no-store" },
  });
}

export async function exportReports(env, since) {
  const { results } = await env.DB.prepare(
    `SELECT r.id, r.lake_id, r.day, r.created_at, r.rating, r.grade, r.note, r.lat, r.lon,
            r.gps_source, f.role
     FROM reports r JOIN friends f ON f.id = r.friend_id
     WHERE r.day >= ? ORDER BY r.created_at`,
  ).bind(since).all();
  return results;
}

export async function getExport(env, request) {
  await requireService(env, request);
  const since = new URL(request.url).searchParams.get("since") || "2000-01-01";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(since)) throw new HttpError(400, "Bad since");
  return json({ reports: await exportReports(env, since) });
}
