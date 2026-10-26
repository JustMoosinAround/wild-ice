import test from "node:test";
import assert from "node:assert/strict";
import {
  buildRatingFile, buildPrefFile, saveFile, enqueue, flushQueue,
  QUEUE_KEY, CREDS_KEY,
} from "../../site/ratings.js";

function fakeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
  };
}
const creds = { token: "tok123", repo: "me/wildice" };
const queueOf = (s) => JSON.parse(s.getItem(QUEUE_KEY) || "[]");

test("rating file path and content", () => {
  const f = buildRatingFile("w1", "skated", "glassy", new Date("2025-11-12T18:00:00Z"));
  assert.match(f.path, /^ratings\/2025-11-12-\d+-w1\.json$/);
  assert.deepEqual(JSON.parse(f.content),
    { lake_id: "w1", day: "2025-11-12", rating: "skated", note: "glassy" });
});

test("bad rating throws", () => {
  assert.throws(() => buildRatingFile("w1", "great", "", new Date()), /rating/);
});

test("pref file path and content", () => {
  const now = new Date("2025-11-12T18:00:00Z");
  const f = buildPrefFile("r9", "pin", now);
  assert.equal(f.path, `prefs/${now.getTime()}-r9.json`);
  assert.deepEqual(JSON.parse(f.content), { lake_id: "r9", action: "pin" });
  assert.throws(() => buildPrefFile("r9", "star", now), /action/);
});

test("saveFile sends PUT with base64 and bearer token", async () => {
  const calls = [];
  const fetchFn = async (url, opts) => { calls.push([url, opts]); return { ok: true, status: 201 }; };
  const file = { path: "ratings/x.json", content: '{"note":"café ❄"}' };
  await saveFile(file, creds, fetchFn);
  const [url, opts] = calls[0];
  assert.equal(url, "https://api.github.com/repos/me/wildice/contents/ratings/x.json");
  assert.equal(opts.method, "PUT");
  assert.equal(opts.headers.Authorization, "Bearer tok123");
  const body = JSON.parse(opts.body);
  assert.equal(Buffer.from(body.content, "base64").toString("utf8"), file.content);
  assert.ok(body.message);
});

test("saveFile rejects on non-2xx without leaking the token", async () => {
  const fetchFn = async () => ({ ok: false, status: 401 });
  await assert.rejects(saveFile({ path: "a.json", content: "{}" }, creds, fetchFn),
    (e) => /401/.test(e.message) && !e.message.includes("tok123"));
});

test("failed save stays queued", async () => {
  const s = fakeStorage();
  s.setItem(CREDS_KEY, JSON.stringify(creds));
  enqueue(s, { path: "a.json", content: "{}" });
  const n = await flushQueue(s, creds, async () => ({ ok: false, status: 500 }));
  assert.equal(n, 0);
  assert.equal(queueOf(s).length, 1);
});

test("queue flushes in order and keeps failures", async () => {
  const s = fakeStorage();
  for (const p of ["a", "b", "c"]) enqueue(s, { path: `${p}.json`, content: "{}" });
  const seen = [];
  const fetchFn = async (url) => {
    seen.push(url.split("/contents/")[1]);
    return url.endsWith("b.json") ? { ok: false, status: 500 } : { ok: true, status: 201 };
  };
  const n = await flushQueue(s, creds, fetchFn);
  assert.equal(n, 2);
  assert.deepEqual(seen, ["a.json", "b.json", "c.json"]);
  assert.deepEqual(queueOf(s).map((f) => f.path), ["b.json"]);
});

test("network error keeps item queued", async () => {
  const s = fakeStorage();
  enqueue(s, { path: "a.json", content: "{}" });
  const n = await flushQueue(s, creds, async () => { throw new TypeError("offline"); });
  assert.equal(n, 0);
  assert.equal(queueOf(s).length, 1);
});

test("flush with no creds is a no-op", async () => {
  const s = fakeStorage();
  enqueue(s, { path: "a.json", content: "{}" });
  assert.equal(await flushQueue(s, null, async () => { throw new Error("no"); }), 0);
  assert.equal(queueOf(s).length, 1);
});

test("401/403/404 signals creds problem and keeps everything queued", async () => {
  for (const status of [401, 403, 404]) {
    const s = fakeStorage();
    enqueue(s, { path: "a.json", content: "{}" });
    enqueue(s, { path: "b.json", content: "{}" });
    let calls = 0, signalled = 0;
    const n = await flushQueue(s, creds, async () => { calls++; return { ok: false, status }; },
      { onAuthFailed: () => { signalled++; } });
    assert.equal(n, 0);
    assert.equal(signalled, 1);
    assert.equal(calls, 1, "stops after the first auth failure");
    assert.deepEqual(queueOf(s).map((f) => f.path), ["a.json", "b.json"]);
  }
});

test("422 (already exists) is dropped and counted as saved", async () => {
  const s = fakeStorage();
  enqueue(s, { path: "a.json", content: "{}" });
  enqueue(s, { path: "b.json", content: "{}" });
  const n = await flushQueue(s, creds, async (url) =>
    url.endsWith("a.json") ? { ok: false, status: 422 } : { ok: true, status: 201 });
  assert.equal(n, 2);
  assert.equal(queueOf(s).length, 0);
});
