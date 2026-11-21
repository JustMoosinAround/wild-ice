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

// Send queued reports in order. 401 = this phone's invite was switched off: forget the
// key and the queue. 400/413 = the report can never succeed: drop it. Network or server
// trouble: stop and keep the rest for next time.
export async function flushReports({ fetch, storage, base }) {
  const device = getDevice(storage);
  let q = queuedReports(storage);
  const out = { sent: 0, left: q.length, revoked: false };
  if (!device || !q.length) return out;
  const rejected = [];
  while (q.length) {
    let res;
    try {
      res = await call(base, "/api/reports", { fetch, method: "POST", body: q[0], token: device.key });
    } catch {
      break;
    }
    if (res.status === 401) {
      clearDevice(storage);
      write(storage, QUEUE_KEY, []);
      return { sent: out.sent, left: 0, revoked: true };
    }
    if (res.status === 200) out.sent++;
    else if (res.status >= 400 && res.status < 500) rejected.push(res.data.error || `HTTP ${res.status}`);
    else break;
    q = q.slice(1);
    write(storage, QUEUE_KEY, q);
  }
  out.left = q.length;
  if (rejected.length) out.rejected = rejected;
  return out;
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
