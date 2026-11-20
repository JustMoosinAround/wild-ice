// The owner's review queue: waiting comments and photos, friends, and pin/hide prefs.
import { requireOwner } from "./auth.js";
import { HttpError, json, now, readJson } from "./http.js";

const MAX_FEATURED = 6;
const PREF_ACTIONS = ["pin", "unpin", "hide", "unhide"];

export async function getReview(env, request) {
  await requireOwner(env, request);
  const comments = await env.DB.prepare(
    `SELECT id, lake_id, name, text, created_at FROM comments WHERE status = 'pending'
     ORDER BY created_at`).all();
  const photos = await env.DB.prepare(
    `SELECT p.id, p.public_id, p.lake_id, f.name AS credit, p.created_at
     FROM photos p LEFT JOIN friends f ON f.id = p.friend_id
     WHERE p.status = 'pending' ORDER BY p.created_at`).all();
  const friends = await env.DB.prepare(
    "SELECT id, name, role, revoked_at FROM friends ORDER BY created_at").all();
  return json({
    comments: comments.results,
    photos: photos.results,
    friends: friends.results.map((f) => ({ id: f.id, name: f.name, role: f.role, revoked: Boolean(f.revoked_at) })),
  });
}

async function action(request, allowed) {
  const { action: a } = await readJson(request);
  if (!allowed.includes(a)) throw new HttpError(400, `Action must be ${allowed.join(" or ")}`);
  return a;
}

export async function reviewComment(env, request, id) {
  await requireOwner(env, request);
  const a = await action(request, ["approve", "reject"]);
  const r = await env.DB.prepare(
    "UPDATE comments SET status = ? WHERE id = ? AND status = 'pending'",
  ).bind(a === "approve" ? "published" : "rejected", id).run();
  if (r.meta.changes !== 1) throw new HttpError(404, "No such waiting comment");
  return json({ ok: true });
}

async function dropPhoto(env, publicId, id) {
  await env.PHOTOS.delete(`photo:${publicId}`);
  await env.DB.prepare("UPDATE photos SET status = 'rejected', decided_at = ? WHERE id = ?")
    .bind(now(), id).run();
}

export async function reviewPhoto(env, request, id) {
  await requireOwner(env, request);
  const a = await action(request, ["feature", "reject"]);
  const p = await env.DB.prepare("SELECT * FROM photos WHERE id = ? AND status = 'pending'").bind(id).first();
  if (!p) throw new HttpError(404, "No such waiting photo");
  if (a === "reject") {
    await dropPhoto(env, p.public_id, p.id);
    return json({ ok: true });
  }
  await env.DB.prepare("UPDATE photos SET status = 'featured', decided_at = ? WHERE id = ?")
    .bind(now(), p.id).run();
  // Keep the newest MAX_FEATURED per lake; older ones are retired and their bytes freed.
  const { results } = await env.DB.prepare(
    `SELECT id, public_id FROM photos WHERE lake_id = ? AND status = 'featured'
     ORDER BY decided_at DESC, rowid DESC LIMIT -1 OFFSET ?`,
  ).bind(p.lake_id, MAX_FEATURED).all();
  for (const old of results) await dropPhoto(env, old.public_id, old.id);
  return json({ ok: true });
}

export async function postPref(env, request) {
  await requireOwner(env, request);
  const body = await readJson(request);
  if (typeof body.lake_id !== "string" || !/^[wr]\d{1,12}$/.test(body.lake_id)) throw new HttpError(400, "Unknown lake");
  if (!PREF_ACTIONS.includes(body.action)) throw new HttpError(400, "Unknown action");
  await env.DB.prepare("INSERT INTO prefs (lake_id, action, created_at) VALUES (?, ?, ?)")
    .bind(body.lake_id, body.action, now()).run();
  return json({ ok: true });
}

export async function exportPrefs(env) {
  const { results } = await env.DB.prepare(
    "SELECT lake_id, action, created_at FROM prefs ORDER BY id").all();
  return results;
}

export async function pendingCounts(env, olderThan = null) {
  const cut = olderThan ?? "9999";
  const c = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM comments WHERE status = 'pending' AND created_at < ?").bind(cut).first("n");
  const p = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM photos WHERE status = 'pending' AND created_at < ?").bind(cut).first("n");
  return { comments: c, photos: p };
}

export async function featuredPhotos(env, lakeId) {
  const { results } = await env.DB.prepare(
    `SELECT p.public_id, f.name AS credit, p.created_at
     FROM photos p LEFT JOIN friends f ON f.id = p.friend_id
     WHERE p.lake_id = ? AND p.status = 'featured' ORDER BY p.created_at DESC LIMIT ?`,
  ).bind(lakeId, MAX_FEATURED).all();
  return results;
}
