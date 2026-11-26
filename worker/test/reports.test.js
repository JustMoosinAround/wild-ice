import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { call, friend, owner } from "./helpers.js";

const JPEG = btoa(String.fromCharCode(0xff, 0xd8, 0xff, 0xe0, ...new Array(200).fill(7)));

function report(extra = {}) {
  return { idem_key: crypto.randomUUID(), lake_id: "w123", rating: "skated", grade: "B+", ...extra };
}

async function exported() {
  const r = await call("GET", "/api/export?since=2000-01-01", { token: "test-service" });
  expect(r.status).toBe(200);
  return (await r.json()).reports;
}

describe("reports", () => {
  it("report saved and exported", async () => {
    const fk = await friend(await owner(), "Pat");
    const r = await call("POST", "/api/reports", { body: report({ note: "glassy" }), token: fk });
    expect(r.status).toBe(200);
    const rows = await exported();
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ lake_id: "w123", rating: "skated", grade: "B+", note: "glassy",
      role: "friend", lat: null, gps_source: null });
    expect(JSON.stringify(rows)).not.toContain("Pat");
    expect(rows[0].friend_id).toBeUndefined();
  });

  it("same idem_key twice saves once", async () => {
    const fk = await friend(await owner());
    const body = report();
    const a = await (await call("POST", "/api/reports", { body, token: fk })).json();
    const second = await call("POST", "/api/reports", { body, token: fk });
    expect(second.status).toBe(200);
    expect((await second.json()).id).toBe(a.id);
    expect(await exported()).toHaveLength(1);
  });

  it("grade rules", async () => {
    const fk = await friend(await owner());
    const post = (b) => call("POST", "/api/reports", { body: report(b), token: fk });
    expect((await post({ rating: "water", grade: "B" })).status).toBe(400);
    expect((await post({ rating: "skated", grade: "E" })).status).toBe(400);
    expect((await post({ rating: "skated", grade: "F-" })).status).toBe(200);
    expect((await post({ rating: "rough", grade: "A+" })).status).toBe(200);
    expect((await post({ rating: "snow", grade: undefined })).status).toBe(200);
  });

  it("other field rules", async () => {
    const fk = await friend(await owner());
    const post = (b) => call("POST", "/api/reports", { body: report(b), token: fk });
    expect((await post({ lake_id: "x1" })).status).toBe(400);
    expect((await post({ rating: "great" })).status).toBe(400);
    expect((await post({ note: "x".repeat(301) })).status).toBe(400);
    expect((await post({ day: "2099-01-01" })).status).toBe(400);
    expect((await post({ day: "2000-01-01" })).status).toBe(400);
    expect((await post({ gps: { lat: 95, lon: -149, source: "photo" } })).status).toBe(400);
    expect((await post({ gps: { lat: 61, lon: -149, source: "guess" } })).status).toBe(400);
    expect((await post({ idem_key: "" })).status).toBe(400);
  });

  it("report with gps is exported with it", async () => {
    const fk = await friend(await owner());
    await call("POST", "/api/reports", { body: report({ gps: { lat: 61.5, lon: -149.2, source: "device" } }), token: fk });
    expect((await exported())[0]).toMatchObject({ lat: 61.5, lon: -149.2, gps_source: "device" });
  });

  it("report without gps is accepted", async () => {
    const fk = await friend(await owner());
    expect((await call("POST", "/api/reports", { body: report(), token: fk })).status).toBe(200);
    expect((await exported())[0]).toMatchObject({ lat: null, lon: null, gps_source: null });
  });

  it("owner reports export as owner", async () => {
    const ok = await owner();
    await call("POST", "/api/reports", { body: report(), token: ok });
    expect((await exported())[0].role).toBe("owner");
  });

  it("photo shows at once (awaiting the owner's look), and not once removed", async () => {
    const ok = await owner();
    const fk = await friend(ok);
    expect((await call("POST", "/api/reports", { body: report({ photo: JPEG }), token: fk })).status).toBe(200);
    const p = await env.DB.prepare("SELECT * FROM photos").first();
    expect(p).toMatchObject({ lake_id: "w123", status: "pending" });
    expect(p.public_id).not.toBe(p.id);
    const pub = await call("GET", `/api/photos/${p.public_id}`);
    expect(pub.status).toBe(200);
    expect(pub.headers.get("Content-Type")).toBe("image/jpeg");
    expect(new Uint8Array(await pub.arrayBuffer())[0]).toBe(0xff);
    await env.DB.prepare("UPDATE photos SET status = 'rejected'").run();
    expect((await call("GET", `/api/photos/${p.public_id}`)).status).toBe(404);
  });

  it("non-JPEG or oversize photo rejected", async () => {
    const fk = await friend(await owner());
    const png = btoa(String.fromCharCode(0x89, 0x50, 0x4e, 0x47, 1, 2, 3));
    expect((await call("POST", "/api/reports", { body: report({ photo: png }), token: fk })).status).toBe(400);
    const big = btoa(String.fromCharCode(0xff, 0xd8, 0xff) + "x".repeat(1_600_000));
    expect((await call("POST", "/api/reports", { body: report({ photo: big }), token: fk })).status).toBe(413);
    expect(await env.DB.prepare("SELECT COUNT(*) AS n FROM reports").first("n")).toBe(0);
  });

  it("revoked device cannot report", async () => {
    const ok = await owner();
    const fk = await friend(ok);
    const id = await env.DB.prepare("SELECT id FROM friends WHERE role = 'friend'").first("id");
    await call("POST", `/api/friends/${id}/revoke`, { token: ok });
    expect((await call("POST", "/api/reports", { body: report(), token: fk })).status).toBe(401);
  });

  it("export needs the service token", async () => {
    expect((await call("GET", "/api/export?since=2000-01-01")).status).toBe(401);
    expect((await call("GET", "/api/export?since=2000-01-01", { token: "nope" })).status).toBe(401);
  });

  it("export since filters by day", async () => {
    const fk = await friend(await owner());
    await call("POST", "/api/reports", { body: report(), token: fk });
    const r = await call("GET", "/api/export?since=2999-01-01", { token: "test-service" });
    expect((await r.json()).reports).toHaveLength(0);
  });
});
