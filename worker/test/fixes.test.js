import { env } from "cloudflare:test";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createExecutionContext, createScheduledController, waitOnExecutionContext } from "cloudflare:test";
import worker from "../src/index.js";
import { call, codeOf, friend, owner } from "./helpers.js";

const JPEG = btoa(String.fromCharCode(0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4));
afterEach(() => vi.restoreAllMocks());

describe("review shows and removes already-public items", () => {
  it("recent reports with notes are on the review page and can be removed", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    await call("POST", "/api/reports", { body: { idem_key: crypto.randomUUID(), lake_id: "w1", rating: "skated", grade: "B", note: "glassy" }, token: fk });
    const r = await (await call("GET", "/api/review", { token: ok })).json();
    expect(r.reports[0]).toMatchObject({ lake_id: "w1", grade: "B", note: "glassy", credit: "Pat" });
    const del = await call("POST", `/api/review/reports/${r.reports[0].id}`, { body: { action: "remove" }, token: ok });
    expect(del.status).toBe(200);
    const e = await (await call("GET", "/api/export?since=2000-01-01", { token: "test-service" })).json();
    expect(e.reports).toHaveLength(0);
  });

  it("a published friend comment can be taken down", async () => {
    const ok = await owner();
    const fk = await friend(ok);
    await call("POST", "/api/comments", { body: { lake_id: "w1", name: "Pat", text: "oops" }, token: fk });
    const r = await (await call("GET", "/api/review", { token: ok })).json();
    expect(r.published[0].text).toBe("oops");
    await call("POST", `/api/review/comments/${r.published[0].id}`, { body: { action: "remove" }, token: ok });
    expect((await (await call("GET", "/api/lakes/w1")).json()).comments).toEqual([]);
  });

  it("a featured photo can be taken down", async () => {
    const ok = await owner();
    const fk = await friend(ok);
    await call("POST", "/api/reports", { body: { idem_key: crypto.randomUUID(), lake_id: "w1", rating: "skated", photo: JPEG }, token: fk });
    const p = await env.DB.prepare("SELECT * FROM photos").first();
    await call("POST", `/api/review/photos/${p.id}`, { body: { action: "feature" }, token: ok });
    const r = await (await call("GET", "/api/review", { token: ok })).json();
    expect(r.featured[0].id).toBe(p.id);
    await call("POST", `/api/review/photos/${p.id}`, { body: { action: "remove" }, token: ok });
    expect((await (await call("GET", "/api/lakes/w1")).json()).photos).toEqual([]);
    expect(await env.PHOTOS.get(`photo:${p.public_id}`)).toBeNull();
  });
});

describe("getting back in", () => {
  it("bootstrap token can mint a new-phone invite for the existing owner", async () => {
    const ok = await owner();
    const r = await call("POST", "/api/bootstrap", { body: {}, token: "test-bootstrap" });
    expect(r.status).toBe(200);
    const d = await (await call("POST", "/api/invites/redeem", { body: { code: codeOf((await r.json()).invite_url) } })).json();
    expect(d.role).toBe("owner");
    expect(await env.DB.prepare("SELECT COUNT(*) AS n FROM friends WHERE role = 'owner'").first("n")).toBe(1);
    expect((await call("GET", "/api/me", { token: ok })).status).toBe(200); // old phone still works
  });

  it("owner can make a new-phone invite for an existing friend", async () => {
    const ok = await owner();
    await friend(ok, "Pat");
    const id = await env.DB.prepare("SELECT id FROM friends WHERE role = 'friend'").first("id");
    const inv = await (await call("POST", "/api/invites", { body: { friend_id: id }, token: ok })).json();
    const d = await (await call("POST", "/api/invites/redeem", { body: { code: codeOf(inv.invite_url), name: "Other" } })).json();
    expect(d).toMatchObject({ role: "friend", name: "Pat" });
    expect(await env.DB.prepare("SELECT COUNT(*) AS n FROM friends WHERE role = 'friend'").first("n")).toBe(1);
    const bad = await call("POST", "/api/invites", { body: { friend_id: "nope" }, token: ok });
    expect(bad.status).toBe(404);
  });
});

describe("revoked keys", () => {
  it("a comment with a bad key gets 401, not the stranger path", async () => {
    const r = await call("POST", "/api/comments", { body: { lake_id: "w1", name: "X", text: "hi" }, token: "not-a-key" });
    expect(r.status).toBe(401);
  });

  it("invited friends comment under their own name", async () => {
    const fk = await friend(await owner(), "Pat");
    await call("POST", "/api/comments", { body: { lake_id: "w1", name: "The Owner", text: "hi" }, token: fk });
    expect((await (await call("GET", "/api/lakes/w1")).json()).comments[0].name).toBe("Pat");
  });
});

describe("cron", () => {
  it("does not re-delete long-rejected photos every day", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("ok"));
    for (let i = 0; i < 5; i++) {
      await env.DB.prepare(`INSERT INTO photos (id, public_id, lake_id, friend_id, created_at, status, decided_at)
        VALUES (?, ?, 'w1', 'f', '2026-01-01T00:00:00Z', 'rejected', '2026-01-02T00:00:00Z')`).bind(`r${i}`, `p${i}`).run();
    }
    const del = vi.spyOn(env.PHOTOS, "delete");
    const ctx = createExecutionContext();
    await worker.scheduled(createScheduledController({ scheduledTime: Date.now(), cron: "x" }), env, ctx);
    await waitOnExecutionContext(ctx);
    expect(del).not.toHaveBeenCalled();
  });
});
