import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { call, friend, owner } from "./helpers.js";

const JPEG = btoa(String.fromCharCode(0xff, 0xd8, 0xff, 0xe0, ...new Array(200).fill(7)));

async function saved(token) {
  const r = await call("GET", "/api/saved", { token });
  expect(r.status).toBe(200);
  return (await r.json()).lakes;
}

function report(extra = {}) {
  return { idem_key: crypto.randomUUID(), lake_id: "w123", rating: "skated", grade: "B+", ...extra };
}

async function exportBody() {
  return (await call("GET", "/api/export?since=2000-01-01", { token: "test-service" })).json();
}

describe("saved lakes", () => {
  it("save, save again, list, delete; each friend has their own list", async () => {
    const ok = await owner();
    const fk = await friend(ok);
    expect((await call("POST", "/api/saved", { body: { lake_id: "w1" }, token: fk })).status).toBe(200);
    expect((await call("POST", "/api/saved", { body: { lake_id: "w1" }, token: fk })).status).toBe(200);
    await call("POST", "/api/saved", { body: { lake_id: "r22" }, token: fk });
    expect((await saved(fk)).sort()).toEqual(["r22", "w1"]);
    expect(await saved(ok)).toEqual([]);
    expect((await call("DELETE", "/api/saved/w1", { token: fk })).status).toBe(200);
    expect(await saved(fk)).toEqual(["r22"]);
  });

  it("needs a device key and a real lake id", async () => {
    const fk = await friend(await owner());
    expect((await call("GET", "/api/saved")).status).toBe(401);
    expect((await call("POST", "/api/saved", { body: { lake_id: "nope" }, token: fk })).status).toBe(400);
  });
});

describe("skated list", () => {
  it("lists this friend's skated and rough lakes, newest day per lake", async () => {
    const ok = await owner();
    const fk = await friend(ok);
    await call("POST", "/api/reports", { body: report({ lake_id: "w1", day: "2026-01-02" }), token: fk });
    await call("POST", "/api/reports", { body: report({ lake_id: "w1", day: "2026-01-05",
      track_minutes: 30, gps: { lat: 61, lon: -149, source: "device" } }), token: fk });
    await call("POST", "/api/reports", { body: report({ lake_id: "w2", rating: "water", grade: null }), token: fk });
    await call("POST", "/api/reports", { body: report({ lake_id: "w3" }), token: ok });
    const r = await call("GET", "/api/me/skated", { token: fk });
    expect((await r.json()).lakes).toEqual([{ lake_id: "w1", day: "2026-01-05" }]);
  });
});

describe("track reports", () => {
  it("track_minutes needs 10-1440 and a location; old tracks are fine", async () => {
    const fk = await friend(await owner());
    const gps = { lat: 61, lon: -149, source: "device" };
    expect((await call("POST", "/api/reports", { body: report({ track_minutes: 5, gps }), token: fk })).status).toBe(400);
    expect((await call("POST", "/api/reports", { body: report({ track_minutes: 42 }), token: fk })).status).toBe(400);
    const r = await call("POST", "/api/reports", { body: report({ track_minutes: 42, gps, day: "2024-01-25" }), token: fk });
    expect(r.status).toBe(200);
    // a plain report still can't be that old
    expect((await call("POST", "/api/reports", { body: report({ day: "2024-01-25" }), token: fk })).status).toBe(400);
    const rows = (await exportBody()).reports;
    expect(rows[0].track_minutes).toBe(42);
  });
});

describe("export featured photos", () => {
  it("only featured photos, with their lake", async () => {
    const ok = await owner();
    const fk = await friend(ok);
    await call("POST", "/api/reports", { body: report({ photo: JPEG }), token: fk });
    await call("POST", "/api/reports", { body: report({ photo: JPEG, lake_id: "w9" }), token: fk });
    expect((await exportBody()).featured).toEqual([]);
    const pid = (await env.DB.prepare("SELECT id FROM photos WHERE lake_id = 'w123'").first()).id;
    expect((await call("POST", `/api/review/photos/${pid}`, { body: { action: "feature" }, token: ok })).status).toBe(200);
    const feat = (await exportBody()).featured;
    expect(feat).toHaveLength(1);
    expect(feat[0]).toMatchObject({ lake_id: "w123" });
    expect(typeof feat[0].public_id).toBe("string");
  });
});

describe("cors", () => {
  it("the site may DELETE a saved lake", async () => {
    const r = await call("OPTIONS", "/api/saved/w1", { headers: { "Access-Control-Request-Method": "DELETE" } });
    expect(r.headers.get("Access-Control-Allow-Methods")).toContain("DELETE");
  });
});
