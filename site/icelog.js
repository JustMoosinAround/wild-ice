// Ice Log browser client: this phone's device key, the offline report queue, photo
// preparation and calls to the Cloudflare worker. ES module, no dependencies; the
// non-DOM parts are tested in node (tests/js/icelog.test.mjs).

export const GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-",
  "D+", "D", "D-", "F+", "F", "F-"];
export const GOOD_GRADE_MIN = "C-"; // owner: A+ ... C- is worth the drive
const DEVICE_KEY = "wildice.device";
const QUEUE_KEY = "wildice.icelog.queue";
const MAX_QUEUED_PHOTOS = 3; // a resized photo is ~300 KB; browser storage is ~5 MB

export function isGoodGrade(grade, min = GOOD_GRADE_MIN) {
  return GRADES.indexOf(grade) <= GRADES.indexOf(min);
}

function read(storage, key, fallback) {
  try { return JSON.parse(storage.getItem(key)) ?? fallback; } catch { return fallback; }
}

function write(storage, key, value) {
  try { storage.setItem(key, JSON.stringify(value)); } catch { /* storage full or blocked */ }
}

export function getDevice(storage) { return read(storage, DEVICE_KEY, null); }
export function setDevice(storage, device) { write(storage, DEVICE_KEY, device); }
export function clearDevice(storage) {
  try { storage.removeItem(DEVICE_KEY); } catch { /* ignore */ }
}

export function queuedReports(storage) { return read(storage, QUEUE_KEY, []); }

// Add a report to the send queue. Its idem_key lets the worker save a resend once.
export function queueReport(storage, report) {
  const q = queuedReports(storage);
  q.push({ ...report, idem_key: crypto.randomUUID() });
  let photos = q.filter((r) => r.photo).length;
  for (const r of q) {
    if (photos <= MAX_QUEUED_PHOTOS) break;
    if (r.photo) { delete r.photo; photos--; }
  }
  write(storage, QUEUE_KEY, q);
}

async function call(base, path, { fetch, method = "GET", body, token }) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(`${base}${path}`, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {};
  try { data = await r.json(); } catch { /* empty or not JSON */ }
  return { status: r.status, data };
}

const MAX_TRIES = 6;        // network/server failures before a report is given up
const PHOTO_TRIES = 3;      // ...and before its photo is dropped (it may be what fails)
let inflight = null;

function updateQueue(storage, fn) {
  write(storage, QUEUE_KEY, fn(queuedReports(storage)));
}

// Send queued reports in order, one send at a time (a second call waits for the first).
// 401 = this phone's invite was switched off: forget the key and the queue. 400/413 =
// the report can never succeed: drop it. Network or server trouble: count a try, keep
// it for later, and stop; a report that keeps failing loses its photo, then gives up,
// so it can never block the ones behind it.
export function flushReports(opts) {
  const run = () => sendAll(opts);
  inflight = (inflight || Promise.resolve()).then(run, run);
  return inflight;
}

async function sendAll({ fetch, storage, base }) {
  const device = getDevice(storage);
  const out = { sent: 0, left: queuedReports(storage).length, revoked: false };
  if (!device || !out.left) return out;
  const rejected = [];
  for (;;) {
    const head = queuedReports(storage)[0];
    if (!head) break;
    const drop = () => updateQueue(storage, (q) => q.filter((r) => r.idem_key !== head.idem_key));
    let res = null;
    try {
      const { tries, ...body } = head;
      res = await call(base, "/api/reports", { fetch, method: "POST", body, token: device.key });
    } catch { /* network trouble: handled below */ }
    if (res && res.status === 401) {
      clearDevice(storage);
      write(storage, QUEUE_KEY, []);
      return { sent: out.sent, left: 0, revoked: true };
    }
    if (res && res.status === 200) { out.sent++; drop(); continue; }
    if (res && res.status >= 400 && res.status < 500) {
      rejected.push(res.data.error || `HTTP ${res.status}`);
      drop();
      continue;
    }
    const tries = (head.tries || 0) + 1;
    if (tries >= MAX_TRIES) {
      rejected.push("Couldn't send a report after several tries");
      drop();
      continue;
    }
    updateQueue(storage, (q) => q.map((r) => {
      if (r.idem_key !== head.idem_key) return r;
      const next = { ...r, tries };
      if (tries >= PHOTO_TRIES) delete next.photo;
      return next;
    }));
    break;
  }
  out.left = queuedReports(storage).length;
  if (rejected.length) out.rejected = rejected;
  return out;
}

// The report to queue: keeps the day it was logged (it may be sent days later).
export function makeReport({ lakeId, rating, grade, note, photo, gps, day }) {
  const r = { lake_id: lakeId, rating };
  if (grade && (rating === "skated" || rating === "rough")) r.grade = grade;
  const n = (note || "").trim().slice(0, 300);
  if (n) r.note = n;
  if (photo) r.photo = photo.jpegBase64;
  const where = photo && photo.gps ? { ...photo.gps, source: "photo" } : gps;
  if (where) r.gps = where;
  r.day = day;
  return r;
}

// At startup: is this phone's key still good? "revoked" clears it (and its queue).
export async function checkDevice({ fetch, storage, base }) {
  const device = getDevice(storage);
  if (!device) return "none";
  try {
    const res = await call(base, "/api/me", { fetch, token: device.key });
    if (res.status === 401) {
      clearDevice(storage);
      write(storage, QUEUE_KEY, []);
      return "revoked";
    }
    return res.status === 200 ? "ok" : "unknown";
  } catch {
    return "unknown";
  }
}

// The map used to save through the owner's GitHub token: remove that token and its old
// queue for good. Returns how many old unsent items were dropped.
export function clearLegacy(storage) {
  const old = read(storage, "wildice.queue", []);
  try {
    storage.removeItem("wildice.creds");
    storage.removeItem("wildice.queue");
  } catch { /* ignore */ }
  return Array.isArray(old) ? old.length : 0;
}

// An invite link opened on a phone that is already signed in.
export function inviteDecision(device) {
  if (!device) return "join";
  return device.role === "owner" ? "refuse" : "confirm";
}

export async function loadLake(lakeId, { fetch, base }) {
  const res = await call(base, `/api/lakes/${encodeURIComponent(lakeId)}`, { fetch });
  return res.status === 200 ? res.data : { comments: [], photos: [] };
}

export async function postComment(comment, { fetch, storage, base }) {
  const device = getDevice(storage);
  try {
    const res = await call(base, "/api/comments", { fetch, method: "POST", body: comment, token: device?.key });
    if (res.status === 200) return { ok: true, status: res.data.status };
    return { ok: false, error: res.data.error || "Couldn't post, try again" };
  } catch {
    return { ok: false, error: "No connection, try again" };
  }
}

export async function redeemInvite(code, name, { fetch, storage, base }) {
  try {
    const res = await call(base, "/api/invites/redeem", { fetch, method: "POST", body: { code, name } });
    if (res.status !== 200) return { ok: false, error: res.data.error || "That invite didn't work" };
    setDevice(storage, { key: res.data.device_key, name: res.data.name, role: res.data.role });
    return { ok: true, name: res.data.name, role: res.data.role };
  } catch {
    return { ok: false, error: "No connection, try again" };
  }
}

// Owner-only calls (review page, pins). Returns {status, data}.
export function ownerCall(path, { fetch, storage, base, method = "GET", body }) {
  return call(base, path, { fetch, method, body, token: getDevice(storage)?.key });
}

// Browser only: read the photo's GPS (if the phone kept it), then redraw it at most
// 1600 px on the long side and re-encode as JPEG, which drops every bit of metadata.
export async function prepPhoto(file) {
  let gps = null;
  try {
    const g = window.exifr ? await window.exifr.gps(file) : null;
    if (g && Number.isFinite(g.latitude) && Number.isFinite(g.longitude)) {
      gps = { lat: g.latitude, lon: g.longitude };
    }
  } catch { /* no GPS: fine */ }
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.82));
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return { jpegBase64: btoa(bin), gps };
}

// "#invite=<code>" from an invite link; null for anything else.
export function inviteCodeFromHash(hash) {
  const m = /^#invite=([A-Za-z0-9_-]{8,128})$/.exec(hash || "");
  return m ? m[1] : null;
}

// A pasted invite link (or bare code), for a home-screen app that can't open links:
// on iPhone it doesn't share storage with Safari, so it has to join by itself.
export function inviteCodeFromText(text) {
  const t = (text || "").trim();
  const i = t.indexOf("#invite=");
  if (i >= 0) return inviteCodeFromHash(t.slice(i));
  return /^[A-Za-z0-9_-]{8,128}$/.test(t) ? t : null;
}

// --- My lakes -------------------------------------------------------------------
// Joined phones keep saved lakes in the worker (synced across their phones); other
// phones keep them in this browser only. Neither calls the worker without a key.
const SAVED_KEY = "wildice.saved";

export async function getSaved({ fetch, storage, base }) {
  const device = getDevice(storage);
  if (!device) return read(storage, SAVED_KEY, []);
  try {
    const res = await call(base, "/api/saved", { fetch, token: device.key });
    return res.status === 200 ? res.data.lakes || [] : [];
  } catch {
    return [];
  }
}

export async function setSaved(lakeId, on, { fetch, storage, base }) {
  const device = getDevice(storage);
  if (!device) {
    const cur = read(storage, SAVED_KEY, []).filter((id) => id !== lakeId);
    write(storage, SAVED_KEY, on ? [...cur, lakeId] : cur);
    return true;
  }
  try {
    const res = on
      ? await call(base, "/api/saved", { fetch, method: "POST", body: { lake_id: lakeId }, token: device.key })
      : await call(base, `/api/saved/${encodeURIComponent(lakeId)}`, { fetch, method: "DELETE", token: device.key });
    return res.status === 200;
  } catch {
    return false;
  }
}

export async function getSkated({ fetch, storage, base }) {
  const device = getDevice(storage);
  if (!device) return [];
  try {
    const res = await call(base, "/api/me/skated", { fetch, token: device.key });
    return res.status === 200 ? res.data.lakes || [] : [];
  } catch {
    return [];
  }
}
