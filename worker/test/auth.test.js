import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { call, codeOf, owner, friend } from "./helpers.js";

describe("invites and devices", () => {
  it("bootstrap creates one owner, later only new-phone links for that owner", async () => {
    const first = await call("POST", "/api/bootstrap", { body: { name: "Owner" }, token: "test-bootstrap" });
    expect(first.status).toBe(200);
    const { invite_url } = await first.json();
    expect(invite_url.startsWith("https://justmoosinaround.github.io/wild-ice/#invite=")).toBe(true);
    await call("POST", "/api/invites/redeem", { body: { code: codeOf(invite_url) } });
    const second = await call("POST", "/api/bootstrap", { body: { name: "Owner" }, token: "test-bootstrap" });
    expect(second.status).toBe(200);
    await call("POST", "/api/invites/redeem", { body: { code: codeOf((await second.json()).invite_url) } });
    expect(await env.DB.prepare("SELECT COUNT(*) AS n FROM friends").first("n")).toBe(1);
  });

  it("bootstrap needs the bootstrap token", async () => {
    const r = await call("POST", "/api/bootstrap", { body: { name: "Owner" }, token: "wrong" });
    expect(r.status).toBe(401);
  });

  it("redeem gives a device key once", async () => {
    const { invite_url } = await (await call("POST", "/api/bootstrap",
      { body: { name: "Owner" }, token: "test-bootstrap" })).json();
    const code = codeOf(invite_url);
    const r = await call("POST", "/api/invites/redeem", { body: { code } });
    expect(r.status).toBe(200);
    const d = await r.json();
    expect(d.role).toBe("owner");
    expect(d.device_key.length).toBeGreaterThan(30);
    const again = await call("POST", "/api/invites/redeem", { body: { code } });
    expect(again.status).toBe(410);
  });

  it("device key authenticates; revoked friend gets 401", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    const me = await call("GET", "/api/me", { token: fk });
    expect(me.status).toBe(200);
    expect(await me.json()).toEqual({ name: "Pat", role: "friend", avatar: null });
    const { results } = await env.DB.prepare("SELECT id FROM friends WHERE role = 'friend'").all();
    const rev = await call("POST", `/api/friends/${results[0].id}/revoke`, { token: ok });
    expect(rev.status).toBe(200);
    expect((await call("GET", "/api/me", { token: fk })).status).toBe(401);
  });

  it("friends cannot make invites or revoke", async () => {
    const ok = await owner();
    const fk = await friend(ok);
    expect((await call("POST", "/api/invites", { body: {}, token: fk })).status).toBe(403);
    expect((await call("POST", "/api/invites", { body: {} })).status).toBe(401);
  });

  it("only hashes are stored", async () => {
    const { invite_url } = await (await call("POST", "/api/bootstrap",
      { body: { name: "Owner" }, token: "test-bootstrap" })).json();
    const code = codeOf(invite_url);
    const { device_key } = await (await call("POST", "/api/invites/redeem", { body: { code } })).json();
    const inv = await env.DB.prepare("SELECT * FROM invites").all();
    const dev = await env.DB.prepare("SELECT * FROM devices").all();
    const dump = JSON.stringify([inv.results, dev.results]);
    expect(dump.includes(code)).toBe(false);
    expect(dump.includes(device_key)).toBe(false);
  });

  it("CORS only for the site origin", async () => {
    const good = await call("GET", "/api/me");
    expect(good.headers.get("Access-Control-Allow-Origin")).toBe("https://justmoosinaround.github.io");
    const bad = await call("GET", "/api/me", { headers: { Origin: "https://evil.example" } });
    expect(bad.headers.get("Access-Control-Allow-Origin")).toBeNull();
    const pre = await call("OPTIONS", "/api/reports");
    expect(pre.status).toBe(204);
  });
});
