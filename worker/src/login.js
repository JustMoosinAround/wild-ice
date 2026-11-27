// Username/email/password accounts. A login makes a device key, like the rest of the API
// uses; passwords are kept only as salted PBKDF2-SHA256 hashes.
import { hash, newToken, requireDevice, requireOwner } from "./auth.js";
import { phoneLabel } from "./account.js";
import { verifyTurnstile } from "./comments.js";
import { HttpError, json, now, readJson } from "./http.js";

const ITERATIONS = 100_000;        // the most Workers' Web Crypto allows
const USERNAME = /^[A-Za-z0-9_.-]{3,30}$/;
const EMAIL = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$/;
const FAILS_PER_HOUR = 10;
const SIGNUPS_PER_DAY = 3;
const RESET_HOURS = 2;

const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

export async function hashPassword(password, saltHex) {
  const salt = saltHex ? Uint8Array.from(saltHex.match(/../g).map((h) => parseInt(h, 16))) : crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: ITERATIONS }, key, 256);
  return { hash: hex(bits), salt: hex(salt) };
}

function same(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

function checkUsername(u) {
  const v = typeof u === "string" ? u.trim() : "";
  if (!USERNAME.test(v)) throw new HttpError(400, "Username: 3-30 letters, numbers, . _ or -");
  return v;
}
function checkEmail(e) {
  const v = typeof e === "string" ? e.trim().toLowerCase() : "";
  if (!EMAIL.test(v)) throw new HttpError(400, "Check your email address");
  return v;
}
function checkPassword(p) {
  if (typeof p !== "string" || p.length < 8 || p.length > 200) throw new HttpError(400, "Password: at least 8 characters");
  return p;
}

async function taken(env, username, email, exceptId = "") {
  const u = await env.DB.prepare("SELECT 1 FROM friends WHERE lower(username) = lower(?) AND id != ?").bind(username, exceptId).first();
  if (u) throw new HttpError(409, "That username is taken");
  const e = await env.DB.prepare("SELECT 1 FROM friends WHERE lower(email) = lower(?) AND id != ?").bind(email, exceptId).first();
  if (e) throw new HttpError(409, "That email already has an account: log in instead");
}

async function newDevice(env, request, friendId) {
  const key = newToken();
  await env.DB.prepare("INSERT INTO devices (key_hash, friend_id, created_at, label) VALUES (?, ?, ?, ?)")
    .bind(await hash(key), friendId, now(), phoneLabel(request.headers.get("User-Agent"))).run();
  return key;
}

export async function signup(env, request) {
  const b = await readJson(request);
  const username = checkUsername(b.username), email = checkEmail(b.email), password = checkPassword(b.password);
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const joinHash = await hash(`join:${ip}`);
  const since = new Date(Date.now() - 86400e3).toISOString();
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM friends WHERE join_hash = ? AND created_at > ?").bind(joinHash, since).first("n");
  if (n >= SIGNUPS_PER_DAY) throw new HttpError(429, "Too many sign-ups from here today, try again tomorrow");
  if (!(await verifyTurnstile(env, b.turnstile_token, ip))) throw new HttpError(403, "Please complete the check and try again");
  await taken(env, username, email);
  const p = await hashPassword(password);
  const id = crypto.randomUUID();
  await env.DB.prepare(
    `INSERT INTO friends (id, name, role, created_at, join_hash, username, email, pass_hash, pass_salt)
     VALUES (?, ?, 'friend', ?, ?, ?, ?, ?, ?)`,
  ).bind(id, username, now(), joinHash, username, email, p.hash, p.salt).run();
  return json({ device_key: await newDevice(env, request, id), name: username, role: "friend" });
}

export async function login(env, request) {
  const b = await readJson(request);
  const who = typeof b.login === "string" ? b.login.trim() : "";
  if (!who || typeof b.password !== "string") throw new HttpError(400, "Enter your username or email and password");
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const failKey = await hash(`login:${ip}`);
  const since = new Date(Date.now() - 3600e3).toISOString();
  const fails = await env.DB.prepare("SELECT COUNT(*) AS n FROM login_fails WHERE key_hash = ? AND at > ?").bind(failKey, since).first("n");
  if (fails >= FAILS_PER_HOUR) throw new HttpError(429, "Too many tries. Wait an hour or reset your password");
  const f = await env.DB.prepare(
    "SELECT * FROM friends WHERE (lower(username) = lower(?) OR lower(email) = lower(?)) AND revoked_at IS NULL").bind(who, who).first();
  const ok = f && f.pass_hash && same((await hashPassword(b.password, f.pass_salt)).hash, f.pass_hash);
  if (!ok) {
    await env.DB.prepare("INSERT INTO login_fails (key_hash, at) VALUES (?, ?)").bind(failKey, now()).run();
    throw new HttpError(401, "Wrong username or password");
  }
  return json({ device_key: await newDevice(env, request, f.id), name: f.name, role: f.role });
}

// An existing account sets (or changes) its username, email and password.
export async function setLogin(env, request) {
  const me = await requireDevice(env, request);
  const b = await readJson(request);
  const f = await env.DB.prepare("SELECT * FROM friends WHERE id = ?").bind(me.id).first();
  if (f.pass_hash) {
    if (typeof b.current_password !== "string" || !same((await hashPassword(b.current_password, f.pass_salt)).hash, f.pass_hash)) {
      throw new HttpError(403, "Current password is wrong");
    }
  }
  const username = checkUsername(b.username ?? f.username), email = checkEmail(b.email ?? f.email);
  const password = b.password ? checkPassword(b.password) : null;
  if (!password && !f.pass_hash) throw new HttpError(400, "Pick a password");
  await taken(env, username, email, me.id);
  const p = password ? await hashPassword(password) : { hash: f.pass_hash, salt: f.pass_salt };
  await env.DB.prepare("UPDATE friends SET username = ?, email = ?, pass_hash = ?, pass_salt = ? WHERE id = ?")
    .bind(username, email, p.hash, p.salt, me.id).run();
  return json({ username, email });
}

export async function loginInfo(env, request) {
  const me = await requireDevice(env, request);
  const f = await env.DB.prepare("SELECT username, email, pass_hash FROM friends WHERE id = ?").bind(me.id).first();
  return json({ username: f.username, email: f.email, has_password: Boolean(f.pass_hash), email_reset: Boolean(env.RESEND_API_KEY) });
}

async function makeReset(env, friendId) {
  const token = newToken();
  await env.DB.prepare("INSERT INTO password_resets (token_hash, friend_id, expires_at) VALUES (?, ?, ?)")
    .bind(await hash(token), friendId, new Date(Date.now() + RESET_HOURS * 3600e3).toISOString()).run();
  return `${env.SITE_URL}/#reset=${token}`;
}

// Forgot password: email a reset link (when email is set up). Same answer either way, so
// nobody can probe which emails have accounts.
export async function forgot(env, request) {
  const b = await readJson(request);
  const email = typeof b.email === "string" ? b.email.trim().toLowerCase() : "";
  const f = email ? await env.DB.prepare("SELECT id, name FROM friends WHERE lower(email) = ? AND revoked_at IS NULL").bind(email).first() : null;
  if (f && env.RESEND_API_KEY && env.MAIL_FROM) {
    const link = await makeReset(env, f.id);
    await fetch("https://api.resend.com/emails", { method: "POST",
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ from: env.MAIL_FROM, to: email, subject: "Reset your Wild Ice password",
        text: `Hi ${f.name},\n\nReset your Wild Ice password here (works for ${RESET_HOURS} hours):\n${link}\n\nDidn't ask? Ignore this email.` }) })
      .catch(() => {});
  }
  return json({ ok: true, email_enabled: Boolean(env.RESEND_API_KEY && env.MAIL_FROM) });
}

export async function reset(env, request) {
  const b = await readJson(request);
  const password = checkPassword(b.password);
  if (typeof b.token !== "string" || !b.token) throw new HttpError(400, "Missing link");
  const th = await hash(b.token);
  const r = await env.DB.prepare("SELECT * FROM password_resets WHERE token_hash = ?").bind(th).first();
  if (!r || r.used_at || r.expires_at < now()) throw new HttpError(410, "This link has expired. Ask for a new one");
  await env.DB.prepare("UPDATE password_resets SET used_at = ? WHERE token_hash = ?").bind(now(), th).run();
  const p = await hashPassword(password);
  await env.DB.prepare("UPDATE friends SET pass_hash = ?, pass_salt = ? WHERE id = ?").bind(p.hash, p.salt, r.friend_id).run();
  const f = await env.DB.prepare("SELECT name, role FROM friends WHERE id = ?").bind(r.friend_id).first();
  return json({ device_key: await newDevice(env, request, r.friend_id), name: f.name, role: f.role });
}

// Owner: a reset link for a member (until email is set up).
export async function ownerReset(env, request, friendId) {
  await requireOwner(env, request);
  const f = await env.DB.prepare("SELECT id FROM friends WHERE id = ? AND revoked_at IS NULL").bind(friendId).first();
  if (!f) throw new HttpError(404, "No such member");
  return json({ reset_url: await makeReset(env, f.id) });
}
