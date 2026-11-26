// Public comments on a lake. Strangers pass Turnstile, a rate limit, and wait for the
// owner's approval; invited friends publish straight away. Comments never feed the model.
import { deviceFriend, hash } from "./auth.js";
import { HttpError, json, now, readJson, PLACE_ID } from "./http.js";

const MAX_TEXT = 500;
const MAX_NAME = 40;
const PER_HOUR = 3;
const LINK = /https?:\/\/|www\.|\.[a-z]{2,}\//i;
const SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify";

export function checkText(text) {
  const t = typeof text === "string" ? text.trim() : "";
  if (!t) return "Write something first";
  if (t.length > MAX_TEXT) return `Keep it under ${MAX_TEXT} characters`;
  if (LINK.test(t)) return "Links aren't allowed in comments";
  return null;
}

export async function verifyTurnstile(env, token, ip) {
  if (typeof token !== "string" || !token) return false;
  const form = new FormData();
  form.append("secret", env.TURNSTILE_SECRET);
  form.append("response", token);
  if (ip) form.append("remoteip", ip);
  try {
    const r = await fetch(SITEVERIFY, { method: "POST", body: form });
    return Boolean((await r.json()).success);
  } catch {
    return false;
  }
}

export async function postComment(env, request) {
  const body = await readJson(request);
  if (typeof body.lake_id !== "string" || !PLACE_ID.test(body.lake_id)) {
    throw new HttpError(400, "Unknown lake");
  }
  const who = await deviceFriend(env, request);
  // A key that no longer works (switched off) is told so, not treated as a stranger.
  if (!who && request.headers.get("Authorization")) throw new HttpError(401, "Not signed in");
  const given = typeof body.name === "string" ? body.name.trim().replace(/\s+/g, " ") : "";
  const name = who ? who.name : given;  // invited friends post under their own name
  if (!name || name.length > MAX_NAME) throw new HttpError(400, `Name must be 1-${MAX_NAME} characters`);
  const problem = checkText(body.text);
  if (problem) throw new HttpError(400, problem);
  const text = body.text.trim();
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const sender = await hash(who ? `friend:${who.id}` : `ip:${ip}`);
  if (!who) {
    const since = new Date(Date.now() - 3600_000).toISOString();
    const n = await env.DB.prepare(
      "SELECT COUNT(*) AS n FROM comments WHERE sender_hash = ? AND created_at > ?",
    ).bind(sender, since).first("n");
    if (n >= PER_HOUR) throw new HttpError(429, "Too many comments, try again later");
    if (!(await verifyTurnstile(env, body.turnstile_token, ip))) {
      throw new HttpError(403, "Please complete the check and try again");
    }
  }
  const status = who ? "published" : "pending";
  await env.DB.prepare(
    `INSERT INTO comments (id, lake_id, name, text, friend_id, sender_hash, created_at, status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind(crypto.randomUUID(), body.lake_id, name, text, who?.id ?? null, sender, now(), status).run();
  return json({ status });
}

export async function lakeComments(env, lakeId) {
  const { results } = await env.DB.prepare(
    `SELECT c.name, c.text, c.created_at, f.avatar_id AS avatar
     FROM comments c LEFT JOIN friends f ON f.id = c.friend_id
     WHERE c.lake_id = ? AND c.status = 'published'
     ORDER BY c.created_at DESC, c.rowid DESC LIMIT 50`,
  ).bind(lakeId).all();
  return results;
}
