import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { call, codeOf, friend, owner } from "./helpers.js";

const JPEG = btoa(String.fromCharCode(0xff, 0xd8, 0xff, 0xe0, ...new Array(200).fill(7)));

function report(extra = {}) {
  return { idem_key: crypto.randomUUID(), lake_id: "w123", rating: "skated", grade: "B+", ...extra };
}

const me = async (token) => (await call("GET", "/api/me", { token })).json();

describe("name and photo", () => {
  it("rename, then the new name shows on later comments", async () => {
    const fk = await friend(await owner(), "Pat");
    expect((await call("PUT", "/api/me", { body: { name: "  Pat  Q " }, token: fk })).status).toBe(200);
    expect((await me(fk)).name).toBe("Pat Q");
    expect((await call("PUT", "/api/me", { body: { name: "" }, token: fk })).status).toBe(400);
  });

  it("profile photo: upload, public URL, replace removes the old one, shows beside comments", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    const r = await call("POST", "/api/me/photo", { body: { photo: JPEG }, token: fk });
    expect(r.status).toBe(200);
    const first = (await me(fk)).avatar;
    expect(first).toMatch(/^[\w-]{20,}$/);
    const img = await call("GET", `/api/avatars/${first}`);
    expect(img.status).toBe(200);
    expect(img.headers.get("Content-Type")).toBe("image/jpeg");
    await call("POST", "/api/me/photo", { body: { photo: JPEG }, token: fk });
    const second = (await me(fk)).avatar;
    expect(second).not.toBe(first);
    expect((await call("GET", `/api/avatars/${first}`)).status).toBe(404);
    expect((await call("POST", "/api/me/photo", { body: { photo: "nope" }, token: fk })).status).toBe(400);
    // a comment by this skater carries the photo
    await call("POST", "/api/comments", { body: { lake_id: "w123", text: "Good ice by the inlet" }, token: fk });
    await env.DB.prepare("UPDATE comments SET status = 'published'").run();
    const lake = await (await call("GET", "/api/lakes/w123")).json();
    expect(lake.comments[0].avatar).toBe(second);
  });
});

describe("my reports", () => {
  it("lists my reports only, and I can delete mine (with its photo) but not others'", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    const mine = await (await call("POST", "/api/reports", { body: report({ photo: JPEG }), token: fk })).json();
    const theirs = await (await call("POST", "/api/reports", { body: report(), token: ok })).json();
    const list = (await (await call("GET", "/api/me/reports", { token: fk })).json()).reports;
    expect(list.map((r) => r.id)).toEqual([mine.id]);
    expect(list[0]).toMatchObject({ lake_id: "w123", rating: "skated", grade: "B+" });
    expect((await call("DELETE", `/api/reports/${theirs.id}`, { token: fk })).status).toBe(404);
    expect((await call("DELETE", `/api/reports/${mine.id}`, { token: fk })).status).toBe(200);
    expect((await (await call("GET", "/api/me/reports", { token: fk })).json()).reports).toEqual([]);
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM photos").first()).n).toBe(0);
  });
});

describe("phones", () => {
  it("lists my phones, signs one out, and makes a link to add another", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    const link = (await (await call("POST", "/api/me/invite", { token: fk })).json()).invite_url;
    const second = (await (await call("POST", "/api/invites/redeem", {
      body: { code: codeOf(link) }, headers: { "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0)" } })).json());
    expect(second.name).toBe("Pat");
    const phones = (await (await call("GET", "/api/me/devices", { token: fk })).json()).devices;
    expect(phones).toHaveLength(2);
    expect(phones.filter((p) => p.current)).toHaveLength(1);
    expect(phones.some((p) => p.label === "iPhone")).toBe(true);
    const other = phones.find((p) => !p.current);
    expect((await call("DELETE", `/api/me/devices/${other.id}`, { token: fk })).status).toBe(200);
    expect((await call("GET", "/api/me", { token: second.device_key })).status).toBe(401);
    expect((await call("GET", "/api/me", { token: fk })).status).toBe(200);
  });
});

describe("download and delete", () => {
  it("download has my profile, reports, comments and saved lakes", async () => {
    const fk = await friend(await owner(), "Pat");
    await call("POST", "/api/reports", { body: report({ note: "glassy" }), token: fk });
    await call("POST", "/api/saved", { body: { lake_id: "w5" }, token: fk });
    const data = await (await call("GET", "/api/me/export", { token: fk })).json();
    expect(data.profile.name).toBe("Pat");
    expect(data.reports[0].note).toBe("glassy");
    expect(data.saved).toEqual(["w5"]);
    expect(Array.isArray(data.comments)).toBe(true);
  });

  it("delete erases name, photo, phones and saved lakes; reports stay anonymous; owner can't", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    await call("POST", "/api/me/photo", { body: { photo: JPEG }, token: fk });
    const avatar = (await me(fk)).avatar;
    await call("POST", "/api/reports", { body: report(), token: fk });
    await call("POST", "/api/comments", { body: { lake_id: "w123", text: "Nice ice today" }, token: fk });
    await call("POST", "/api/saved", { body: { lake_id: "w5" }, token: fk });
    expect((await call("POST", "/api/me/delete", { token: ok })).status).toBe(400);
    expect((await call("POST", "/api/me/delete", { token: fk })).status).toBe(200);
    expect((await call("GET", "/api/me", { token: fk })).status).toBe(401);
    expect((await call("GET", `/api/avatars/${avatar}`)).status).toBe(404);
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM reports").first()).n).toBe(1);
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM saved").first()).n).toBe(0);
    expect((await env.DB.prepare("SELECT name FROM comments").first()).name).toBe("Former skater");
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM friends WHERE name = 'Pat'").first()).n).toBe(0);
  });
});
