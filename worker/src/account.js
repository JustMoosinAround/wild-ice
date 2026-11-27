// The account page: name and photo, my reports, my phones, download and delete.
import { createInvite, hash, newToken, requireDevice } from "./auth.js";
import { HttpError, json, now, readJson } from "./http.js";
import { decodePhoto } from "./reports.js";

const FORMER = "Former skater";

export function phoneLabel(ua) {
  const s = String(ua || "");
  if (/iPhone/.test(s)) return "iPhone";
  if (/iPad/.test(s)) return "iPad";
  if (/Android/.test(s)) return "Android";
  if (/Macintosh/.test(s)) return "Mac";
  if (/Windows/.test(s)) return "Windows";
  return "Browser";
}

export async function putMe(env, request) {
  const who = await requireDevice(env, request);
  const body = await readJson(request);
  const name = typeof body.name === "string" ? body.name.trim().replace(/\s+/g, " ").slice(0, 40) : "";
  if (!name) throw new HttpError(400, "Name can't be empty");
  await env.DB.prepare("UPDATE friends SET name = ? WHERE id = ?").bind(name, who.id).run();
  return json({ ok: true, name });
}

export async function postMyPhoto(env, request) {
  const who = await requireDevice(env, request);
  const bytes = decodePhoto((await readJson(request)).photo);
  const id = newToken();
  await env.PHOTOS.put(`avatar:${id}`, bytes);
  const old = await env.DB.prepare("SELECT avatar_id FROM friends WHERE id = ?").bind(who.id).first("avatar_id");
  await env.DB.prepare("UPDATE friends SET avatar_id = ? WHERE id = ?").bind(id, who.id).run();
  if (old) await env.PHOTOS.delete(`avatar:${old}`);
  return json({ ok: true, avatar: id });
}

export async function getAvatar(env, request, id) {
  const bytes = await env.PHOTOS.get(`avatar:${id}`, "arrayBuffer");
  if (!bytes) throw new HttpError(404, "No such photo");
  return new Response(bytes, { headers: { "Content-Type": "image/jpeg", "Cache-Control": "public, max-age=86400" } });
}

export async function myReports(env, request) {
  const who = await requireDevice(env, request);
  const { results } = await env.DB.prepare(
    `SELECT id, lake_id, day, created_at, rating, grade, note, track_minutes, photo_id IS NOT NULL AS has_photo
     FROM reports WHERE friend_id = ? ORDER BY day DESC, created_at DESC LIMIT 200`,
  ).bind(who.id).all();
  return json({ reports: results });
}

async function removePhoto(env, photoId) {
  if (!photoId) return;
  const p = await env.DB.prepare("SELECT public_id FROM photos WHERE id = ?").bind(photoId).first();
  if (p) await env.PHOTOS.delete(`photo:${p.public_id}`);
  await env.DB.prepare("DELETE FROM photos WHERE id = ?").bind(photoId).run();
}

export async function deleteReport(env, request, id) {
  const who = await requireDevice(env, request);
  const r = await env.DB.prepare("SELECT photo_id FROM reports WHERE id = ? AND friend_id = ?").bind(id, who.id).first();
  if (!r) throw new HttpError(404, "No such report");
  await removePhoto(env, r.photo_id);
  await env.DB.prepare("DELETE FROM reports WHERE id = ?").bind(id).run();
  return json({ ok: true });
}

export async function myDevices(env, request) {
  const who = await requireDevice(env, request);
  const mine = await hash((request.headers.get("Authorization") || "").replace(/^Bearer /, ""));
  const { results } = await env.DB.prepare(
    "SELECT key_hash, label, created_at, last_seen FROM devices WHERE friend_id = ? ORDER BY created_at",
  ).bind(who.id).all();
  return json({ devices: results.map((d) => ({ id: d.key_hash.slice(0, 16), label: d.label || "Browser",
    added: d.created_at, last_seen: d.last_seen || d.created_at, current: d.key_hash === mine })) });
}

export async function deleteMyDevice(env, request, id) {
  const who = await requireDevice(env, request);
  if (!/^[0-9a-f]{16}$/.test(id)) throw new HttpError(404, "No such phone");
  const r = await env.DB.prepare("DELETE FROM devices WHERE friend_id = ? AND substr(key_hash, 1, 16) = ?")
    .bind(who.id, id).run();
  if (r.meta.changes < 1) throw new HttpError(404, "No such phone");
  return json({ ok: true });
}

// A one-time link that signs another phone in as me.
export async function myInvite(env, request) {
  const who = await requireDevice(env, request);
  const { invite_url } = await createInvite(env, { role: who.role, friendId: who.id });
  return json({ invite_url });
}

export async function myExport(env, request) {
  const who = await requireDevice(env, request);
  const q = (sql) => env.DB.prepare(sql).bind(who.id).all().then((r) => r.results);
  return json({
    profile: { name: who.name, role: who.role },
    reports: await q(`SELECT lake_id, day, created_at, rating, grade, note, lat, lon, track_minutes
                      FROM reports WHERE friend_id = ? ORDER BY day`),
    comments: await q("SELECT lake_id, text, created_at, status FROM comments WHERE friend_id = ? ORDER BY created_at"),
    saved: (await q("SELECT lake_id FROM saved WHERE friend_id = ? ORDER BY created_at")).map((r) => r.lake_id),
  }, 200, { "Content-Disposition": 'attachment; filename="wild-ice-my-data.json"' });
}

export async function deleteMe(env, request) {
  const who = await requireDevice(env, request);
  if (who.role === "owner") throw new HttpError(400, "The owner account can't be deleted");
  const avatar = await env.DB.prepare("SELECT avatar_id FROM friends WHERE id = ?").bind(who.id).first("avatar_id");
  if (avatar) await env.PHOTOS.delete(`avatar:${avatar}`);
  await env.DB.batch([
    env.DB.prepare("UPDATE friends SET name = ?, avatar_id = NULL, username = NULL, email = NULL, pass_hash = NULL, pass_salt = NULL, revoked_at = ? WHERE id = ?").bind(FORMER, now(), who.id),
    env.DB.prepare("UPDATE comments SET name = ? WHERE friend_id = ?").bind(FORMER, who.id),
    env.DB.prepare("DELETE FROM devices WHERE friend_id = ?").bind(who.id),
    env.DB.prepare("DELETE FROM saved WHERE friend_id = ?").bind(who.id),
    env.DB.prepare("DELETE FROM strava WHERE friend_id = ?").bind(who.id),
    env.DB.prepare("DELETE FROM invites WHERE friend_id = ? AND used_at IS NULL").bind(who.id),
  ]);
  return json({ ok: true });
}
