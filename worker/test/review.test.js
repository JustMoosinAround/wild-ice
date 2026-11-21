import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { call, friend, owner } from "./helpers.js";

const JPEG = btoa(String.fromCharCode(0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4));

async function photoReport(key, lake = "w123") {
  await call("POST", "/api/reports", {
    body: { idem_key: crypto.randomUUID(), lake_id: lake, rating: "skated", grade: "A", photo: JPEG }, token: key,
  });
  return env.DB.prepare("SELECT * FROM photos ORDER BY created_at DESC, rowid DESC").first();
}

async function strangerComment(text = "Lot is plowed") {
  const id = crypto.randomUUID();
  await env.DB.prepare(
    `INSERT INTO comments (id, lake_id, name, text, sender_hash, created_at, status)
     VALUES (?, 'w123', 'Sam', ?, 'x', ?, 'pending')`,
  ).bind(id, text, new Date().toISOString()).run();
  return id;
}

describe("review", () => {
  it("review lists waiting items and needs the owner", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    await photoReport(fk);
    await strangerComment();
    expect((await call("GET", "/api/review", { token: fk })).status).toBe(403);
    const r = await (await call("GET", "/api/review", { token: ok })).json();
    expect(r.comments).toHaveLength(1);
    expect(r.comments[0]).toMatchObject({ lake_id: "w123", name: "Sam", text: "Lot is plowed" });
    expect(r.photos).toHaveLength(1);
    expect(r.photos[0]).toMatchObject({ lake_id: "w123", credit: "Pat" });
    expect(r.friends.map((f) => [f.name, f.role, f.revoked])).toEqual(
      expect.arrayContaining([["Owner", "owner", false], ["Pat", "friend", false]]));
  });

  it("approve publishes comment; reject hides it", async () => {
    const ok = await owner();
    const a = await strangerComment("first");
    const b = await strangerComment("second");
    expect((await call("POST", `/api/review/comments/${a}`, { body: { action: "approve" }, token: ok })).status).toBe(200);
    await call("POST", `/api/review/comments/${b}`, { body: { action: "reject" }, token: ok });
    const lake = await (await call("GET", "/api/lakes/w123")).json();
    expect(lake.comments.map((c) => c.text)).toEqual(["first"]);
    expect((await call("POST", `/api/review/comments/${a}`, { body: { action: "maybe" }, token: ok })).status).toBe(400);
  });

  it("feature then lake shows photo with credit", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    const p = await photoReport(fk);
    await call("POST", `/api/review/photos/${p.id}`, { body: { action: "feature" }, token: ok });
    const lake = await (await call("GET", "/api/lakes/w123")).json();
    expect(lake.photos).toHaveLength(1);
    expect(lake.photos[0]).toMatchObject({ public_id: p.public_id, credit: "Pat" });
    expect((await call("GET", `/api/photos/${p.public_id}`)).status).toBe(200);
  });

  it("seventh feature drops oldest", async () => {
    const ok = await owner();
    const fk = await friend(ok);
    const ids = [];
    for (let i = 0; i < 7; i++) {
      const p = await photoReport(fk);
      ids.push(p);
      await call("POST", `/api/review/photos/${p.id}`, { body: { action: "feature" }, token: ok });
    }
    const lake = await (await call("GET", "/api/lakes/w123")).json();
    expect(lake.photos).toHaveLength(6);
    expect(lake.photos.map((x) => x.public_id)).not.toContain(ids[0].public_id);
    expect(await env.PHOTOS.get(`photo:${ids[0].public_id}`)).toBeNull();
  });

  it("reject deletes photo bytes", async () => {
    const ok = await owner();
    const p = await photoReport(await friend(ok));
    await call("POST", `/api/review/photos/${p.id}`, { body: { action: "reject" }, token: ok });
    expect(await env.PHOTOS.get(`photo:${p.public_id}`)).toBeNull();
    expect((await env.DB.prepare("SELECT status FROM photos WHERE id = ?").bind(p.id).first("status"))).toBe("rejected");
  });

  it("export pending counts and prefs oldest first", async () => {
    const ok = await owner();
    await photoReport(await friend(ok));
    await strangerComment();
    await strangerComment();
    await call("POST", "/api/prefs", { body: { lake_id: "w1", action: "pin" }, token: ok });
    await call("POST", "/api/prefs", { body: { lake_id: "w1", action: "unpin" }, token: ok });
    expect((await call("POST", "/api/prefs", { body: { lake_id: "w1", action: "nuke" }, token: ok })).status).toBe(400);
    const e = await (await call("GET", "/api/export?since=2000-01-01", { token: "test-service" })).json();
    expect(e.pending).toEqual({ comments: 2, photos: 1 });
    expect(e.prefs.map((p) => [p.lake_id, p.action])).toEqual([["w1", "pin"], ["w1", "unpin"]]);
  });

  it("friends cannot moderate or set prefs", async () => {
    const fk = await friend(await owner());
    expect((await call("POST", "/api/prefs", { body: { lake_id: "w1", action: "pin" }, token: fk })).status).toBe(403);
  });
});
