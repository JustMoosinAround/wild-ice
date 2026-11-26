// On-the-ice reports (with an optional, already resized and metadata-free photo).
import { deviceFriend, newToken, requireDevice, requireService } from "./auth.js";
import { HttpError, json, now, readJson, PLACE_ID } from "./http.js";
import { exportPrefs, pendingCounts } from "./review.js";

export const RATINGS = ["skated", "snow", "water", "rough"];
export const GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-",
  "D+", "D", "D-", "F+", "F", "F-"];
const GRADED = new Set(["skated", "rough"]);
const MAX_PHOTO_BYTES = 1.5 * 1024 * 1024;
const MAX_NOTE = 300;
const MAX_STORY = 1000;
const LINK = /https?:\/\/|www\.|\.[a-z]{2,}\//i;
const MAX_AGE_DAYS = 14;
const MAX_TRACK_AGE_DAYS = 3653; // ~10 years of history from a Strava export

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

export function decodePhoto(b64) {
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
  if (typeof body.lake_id !== "string" || !PLACE_ID.test(body.lake_id)) bad("Unknown lake");
  if (!RATINGS.includes(body.rating)) bad("Pick a condition");
  let grade = body.grade ?? null;
  if (grade !== null) {
    if (!GRADED.has(body.rating)) bad("Grades go with Skateable or Rough ice");
    if (!GRADES.includes(grade)) bad("Unknown grade");
  }
  const note = body.note == null ? "" : String(body.note).trim();
  const story = body.story == null ? "" : String(body.story).trim();
  if (story.length > MAX_STORY) bad(`Trip report is over ${MAX_STORY} characters`);
  if (LINK.test(story)) bad("Links aren't allowed in trip reports");
  if (note.length > MAX_NOTE) bad(`Note is over ${MAX_NOTE} characters`);
  const day = body.day == null ? today : body.day;
  if (typeof day !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(day) || Number.isNaN(Date.parse(day))) bad("Bad day");
  let trackMinutes = null;
  if (body.track_minutes != null) {
    trackMinutes = body.track_minutes;
    if (!Number.isInteger(trackMinutes) || trackMinutes < 10 || trackMinutes > 1440) bad("Bad track time");
    if (body.gps == null) bad("A track report needs a location");
  }
  const age = daysBetween(day, today);
  if (age < 0) bad("That day hasn't happened yet");
  // An uploaded track proves the day, so old trips (history) are allowed.
  if (age > MAX_AGE_DAYS && trackMinutes === null) bad(`Reports must be from the last ${MAX_AGE_DAYS} days`);
  if (age > MAX_TRACK_AGE_DAYS) bad("Tracks must be from the last 10 years");
  let gps = null;
  if (body.gps != null) {
    const { lat, lon, source } = body.gps;
    if (typeof lat !== "number" || typeof lon !== "number" || !Number.isFinite(lat) || !Number.isFinite(lon)
        || lat < -90 || lat > 90 || lon < -180 || lon > 180) bad("Bad location");
    if (source !== "photo" && source !== "device") bad("Bad location source");
    gps = { lat, lon, source };
  }
  const photo = body.photo == null ? null : decodePhoto(body.photo);
  const via = body.via == null ? null : body.via;
  if (via !== null && via !== "strava") bad("Unknown source");
  return { idem, lake_id: body.lake_id, rating: body.rating, grade, note, story: story || null, day, gps, photo, trackMinutes, via };
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
                            lat, lon, gps_source, photo_id, track_minutes, story, via)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(id, r.idem, who.id, r.lake_id, r.day, now(), r.rating, r.grade, r.note,
      r.gps?.lat ?? null, r.gps?.lon ?? null, r.gps?.source ?? null, photoId, r.trackMinutes, r.story, r.via).run();
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
  // Members' photos show at once (the owner can remove them in Review); removed ones don't.
  const allowed = p && p.status !== "rejected";
  const bytes = allowed ? await env.PHOTOS.get(`photo:${publicId}`, "arrayBuffer") : null;
  if (!bytes) throw new HttpError(404, "No such photo");
  return new Response(bytes, {
    headers: { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=3600" },
  });
}

export async function exportReports(env, since) {
  const { results } = await env.DB.prepare(
    `SELECT r.id, r.lake_id, r.day, r.created_at, r.rating, r.grade, r.note, r.lat, r.lon,
            r.gps_source, r.track_minutes, f.role
     FROM reports r JOIN friends f ON f.id = r.friend_id
     WHERE r.day >= ? ORDER BY r.created_at`,
  ).bind(since).all();
  return results;
}

export async function getExport(env, request) {
  await requireService(env, request);
  const since = new URL(request.url).searchParams.get("since") || "2000-01-01";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(since)) throw new HttpError(400, "Bad since");
  return json({
    reports: await exportReports(env, since),
    prefs: await exportPrefs(env),
    pending: await pendingCounts(env),
    // The owner's saved lakes: the daily run checks these every day (they were "pins").
    owner_saved: (await env.DB.prepare(
      `SELECT s.lake_id FROM saved s JOIN friends f ON f.id = s.friend_id
       WHERE f.role = 'owner' AND f.revoked_at IS NULL ORDER BY s.created_at`).all()).results.map((r) => r.lake_id),
    featured: (await env.DB.prepare(
      `SELECT lake_id, public_id, COALESCE(decided_at, created_at) AS created_at
       FROM photos WHERE status = 'featured' ORDER BY created_at`).all()).results,
  });
}
