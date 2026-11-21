import { test } from "node:test";
import assert from "node:assert/strict";
import {
  GRADES, isGoodGrade, getDevice, setDevice, clearDevice, queueReport, queuedReports,
  flushReports, loadLake, postComment, redeemInvite, inviteCodeFromHash,
} from "../../site/icelog.js";

function memStore() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
}

function fakeFetch(handler) {
  const calls = [];
  const f = async (url, init = {}) => {
    calls.push({ url, init, body: init.body ? JSON.parse(init.body) : undefined });
    const [status, body] = await handler(url, init, calls.length);
    return new Response(JSON.stringify(body ?? {}), { status });
  };
  f.calls = calls;
  return f;
}

const BASE = "https://ice.example";

test("GRADES order and isGoodGrade", () => {
  assert.equal(GRADES.length, 15);
  assert.equal(GRADES[0], "A+");
  assert.equal(GRADES.at(-1), "F-");
  assert.equal(isGoodGrade("C-"), true);
  assert.equal(isGoodGrade("D+"), false);
  assert.equal(isGoodGrade("B", "B+"), false);
});

test("device key round trip", () => {
  const s = memStore();
  assert.equal(getDevice(s), null);
  setDevice(s, { key: "k", name: "Pat", role: "friend" });
  assert.deepEqual(getDevice(s), { key: "k", name: "Pat", role: "friend" });
  clearDevice(s);
  assert.equal(getDevice(s), null);
});

test("queued report gets one idem_key and is removed after 200", async () => {
  const s = memStore();
  setDevice(s, { key: "dev", name: "Pat", role: "friend" });
  queueReport(s, { lake_id: "w1", rating: "skated", grade: "B" });
  const key = queuedReports(s)[0].idem_key;
  assert.ok(key && key.length >= 8);
  const f = fakeFetch(() => [200, { id: "r1" }]);
  const r = await flushReports({ fetch: f, storage: s, base: BASE });
  assert.deepEqual(r, { sent: 1, left: 0, revoked: false });
  assert.equal(f.calls[0].url, `${BASE}/api/reports`);
  assert.equal(f.calls[0].init.headers.Authorization, "Bearer dev");
  assert.equal(f.calls[0].body.idem_key, key);
  assert.equal(queuedReports(s).length, 0);
});

test("network error keeps the queue, and the retry reuses the idem_key", async () => {
  const s = memStore();
  setDevice(s, { key: "dev", name: "Pat", role: "friend" });
  queueReport(s, { lake_id: "w1", rating: "water" });
  const key = queuedReports(s)[0].idem_key;
  const down = async () => { throw new TypeError("Failed to fetch"); };
  assert.deepEqual(await flushReports({ fetch: down, storage: s, base: BASE }), { sent: 0, left: 1, revoked: false });
  const f = fakeFetch(() => [200, { id: "r1" }]);
  await flushReports({ fetch: f, storage: s, base: BASE });
  assert.equal(f.calls[0].body.idem_key, key);
});

test("server error keeps the queue; a rejected report is dropped", async () => {
  const s = memStore();
  setDevice(s, { key: "dev", name: "Pat", role: "friend" });
  queueReport(s, { lake_id: "w1", rating: "skated", grade: "Z" });
  queueReport(s, { lake_id: "w2", rating: "snow" });
  const f = fakeFetch((url, init, n) => (n === 1 ? [400, { error: "Unknown grade" }] : [503, {}]));
  const r = await flushReports({ fetch: f, storage: s, base: BASE });
  assert.deepEqual(r, { sent: 0, left: 1, revoked: false, rejected: ["Unknown grade"] });
  assert.equal(queuedReports(s)[0].lake_id, "w2");
});

test("401 clears device and queue and reports revoked", async () => {
  const s = memStore();
  setDevice(s, { key: "dev", name: "Pat", role: "friend" });
  queueReport(s, { lake_id: "w1", rating: "skated" });
  queueReport(s, { lake_id: "w2", rating: "skated" });
  const f = fakeFetch(() => [401, { error: "Not signed in" }]);
  const r = await flushReports({ fetch: f, storage: s, base: BASE });
  assert.equal(r.revoked, true);
  assert.equal(getDevice(s), null);
  assert.equal(queuedReports(s).length, 0);
  assert.equal(f.calls.length, 1);
});

test("fourth queued photo drops the oldest photo but keeps its report", () => {
  const s = memStore();
  for (let i = 0; i < 4; i++) queueReport(s, { lake_id: `w${i}`, rating: "skated", photo: `p${i}` });
  const q = queuedReports(s);
  assert.equal(q.length, 4);
  assert.equal(q[0].photo, undefined);
  assert.deepEqual(q.slice(1).map((r) => r.photo), ["p1", "p2", "p3"]);
});

test("no device: flush does nothing", async () => {
  const s = memStore();
  queueReport(s, { lake_id: "w1", rating: "skated" });
  const f = fakeFetch(() => [200, {}]);
  assert.deepEqual(await flushReports({ fetch: f, storage: s, base: BASE }), { sent: 0, left: 1, revoked: false });
  assert.equal(f.calls.length, 0);
});

test("loadLake and postComment", async () => {
  const s = memStore();
  const f = fakeFetch((url) => (url.endsWith("/api/lakes/w1")
    ? [200, { comments: [{ name: "Sam", text: "hi", created_at: "x" }], photos: [] }]
    : [200, { status: "pending" }]));
  assert.equal((await loadLake("w1", { fetch: f, base: BASE })).comments[0].name, "Sam");
  const r = await postComment({ lake_id: "w1", name: "Sam", text: "hi", turnstile_token: "t" }, { fetch: f, storage: s, base: BASE });
  assert.deepEqual(r, { ok: true, status: "pending" });
  assert.equal(f.calls[1].init.headers.Authorization, undefined);
  setDevice(s, { key: "dev", name: "Pat", role: "friend" });
  await postComment({ lake_id: "w1", name: "Pat", text: "hi" }, { fetch: f, storage: s, base: BASE });
  assert.equal(f.calls[2].init.headers.Authorization, "Bearer dev");
});

test("postComment surfaces the server's message", async () => {
  const f = fakeFetch(() => [429, { error: "Too many comments, try again later" }]);
  const r = await postComment({ lake_id: "w1", name: "S", text: "x" }, { fetch: f, storage: memStore(), base: BASE });
  assert.deepEqual(r, { ok: false, error: "Too many comments, try again later" });
});

test("redeemInvite stores the device", async () => {
  const s = memStore();
  const f = fakeFetch(() => [200, { device_key: "dk", name: "Pat", role: "friend" }]);
  const r = await redeemInvite("code1", "Pat", { fetch: f, storage: s, base: BASE });
  assert.deepEqual(r, { ok: true, name: "Pat", role: "friend" });
  assert.deepEqual(getDevice(s), { key: "dk", name: "Pat", role: "friend" });
  assert.deepEqual(f.calls[0].body, { code: "code1", name: "Pat" });
  const used = fakeFetch(() => [410, { error: "This invite was already used" }]);
  assert.deepEqual(await redeemInvite("code1", "Pat", { fetch: used, storage: memStore(), base: BASE }),
    { ok: false, error: "This invite was already used" });
});

test("inviteCodeFromHash reads only a well-formed invite", () => {
  assert.equal(inviteCodeFromHash("#invite=Qv2lif-B2_sS"), "Qv2lif-B2_sS");
  assert.equal(inviteCodeFromHash("#lake=w1"), null);
  assert.equal(inviteCodeFromHash("#invite="), null);
  assert.equal(inviteCodeFromHash("#invite=<script>"), null);
});
