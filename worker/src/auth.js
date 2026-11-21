// Invites, device keys, roles and the service token. Only SHA-256 hashes are stored.
import { HttpError, json, now, readJson } from "./http.js";

export async function hash(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function newToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function bearer(request) {
  const m = (request.headers.get("Authorization") || "").match(/^Bearer (.+)$/);
  return m ? m[1] : null;
}

// Constant-time comparison of two strings (same-length digests).
async function sameSecret(given, expected) {
  if (!given || !expected) return false;
  const [a, b] = await Promise.all([hash(given), hash(expected)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function deviceFriend(env, request) {
  const key = bearer(request);
  if (!key) return null;
  return await env.DB.prepare(
    `SELECT f.id, f.name, f.role FROM devices d JOIN friends f ON f.id = d.friend_id
     WHERE d.key_hash = ? AND f.revoked_at IS NULL`,
  ).bind(await hash(key)).first();
}

export async function requireDevice(env, request) {
  const f = await deviceFriend(env, request);
  if (!f) throw new HttpError(401, "Not signed in");
  return f;
}

export async function requireOwner(env, request) {
  const f = await requireDevice(env, request);
  if (f.role !== "owner") throw new HttpError(403, "Owner only");
  return f;
}

export async function requireService(env, request) {
  if (!(await sameSecret(bearer(request), env.SERVICE_TOKEN))) throw new HttpError(401, "Bad token");
}

export async function createInvite(env, { role, name = null, friendId = null }) {
  const code = newToken();
  await env.DB.prepare(
    "INSERT INTO invites (code_hash, friend_id, role, name, created_at) VALUES (?, ?, ?, ?, ?)",
  ).bind(await hash(code), friendId, role, name, now()).run();
  return { code, invite_url: `${env.SITE_URL}/#invite=${code}` };
}

function cleanName(value, fallback) {
  const n = typeof value === "string" ? value.trim().replace(/\s+/g, " ") : "";
  return (n || fallback || "").slice(0, 40);
}

export async function bootstrap(env, request) {
  if (!(await sameSecret(bearer(request), env.BOOTSTRAP_TOKEN))) throw new HttpError(401, "Bad token");
  const owner = await env.DB.prepare(
    "SELECT id FROM friends WHERE role = 'owner' AND revoked_at IS NULL").first();
  const body = await readJson(request);
  if (owner) {
    // Owner lost their phone (or its storage): a new-phone link for the same owner.
    const { invite_url } = await createInvite(env, { role: "owner", friendId: owner.id });
    return json({ invite_url });
  }
  const { invite_url } = await createInvite(env, { role: "owner", name: cleanName(body.name, "Owner") });
  return json({ invite_url });
}

export async function redeem(env, request) {
  const body = await readJson(request);
  if (typeof body.code !== "string" || !body.code) throw new HttpError(400, "Missing code");
  const codeHash = await hash(body.code);
  const inv = await env.DB.prepare("SELECT * FROM invites WHERE code_hash = ?").bind(codeHash).first();
  if (!inv) throw new HttpError(404, "Unknown invite");
  // Claim the invite atomically: a second redeem (or a race) finds used_at set.
  const claim = await env.DB.prepare(
    "UPDATE invites SET used_at = ? WHERE code_hash = ? AND used_at IS NULL",
  ).bind(now(), codeHash).run();
  if (claim.meta.changes !== 1) throw new HttpError(410, "This invite was already used");
  let friendId = inv.friend_id;
  let name = cleanName(body.name, inv.name || "Skater");
  if (friendId) {
    const f = await env.DB.prepare("SELECT * FROM friends WHERE id = ?").bind(friendId).first();
    if (!f || f.revoked_at) throw new HttpError(410, "This invite was switched off");
    name = f.name;
  } else {
    friendId = crypto.randomUUID();
    await env.DB.prepare(
      "INSERT INTO friends (id, name, role, created_at) VALUES (?, ?, ?, ?)",
    ).bind(friendId, name, inv.role, now()).run();
  }
  const key = newToken();
  await env.DB.prepare(
    "INSERT INTO devices (key_hash, friend_id, created_at) VALUES (?, ?, ?)",
  ).bind(await hash(key), friendId, now()).run();
  return json({ device_key: key, name, role: inv.role });
}

export async function me(env, request) {
  const f = await requireDevice(env, request);
  return json({ name: f.name, role: f.role });
}

export async function invite(env, request) {
  await requireOwner(env, request);
  const body = await readJson(request);
  if (body.friend_id != null) {
    // New-phone link for an existing friend: same name, same reporter.
    const f = await env.DB.prepare(
      "SELECT id FROM friends WHERE id = ? AND role = 'friend' AND revoked_at IS NULL",
    ).bind(String(body.friend_id)).first();
    if (!f) throw new HttpError(404, "No such friend");
    const { invite_url } = await createInvite(env, { role: "friend", friendId: f.id });
    return json({ invite_url });
  }
  const name = cleanName(body.name, "") || null;
  const { invite_url } = await createInvite(env, { role: "friend", name });
  return json({ invite_url });
}

export async function revoke(env, request, friendId) {
  const owner = await requireOwner(env, request);
  if (friendId === owner.id) throw new HttpError(400, "You can't revoke yourself");
  const r = await env.DB.prepare(
    "UPDATE friends SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
  ).bind(now(), friendId).run();
  if (r.meta.changes !== 1) throw new HttpError(404, "No such friend");
  return json({ ok: true });
}
