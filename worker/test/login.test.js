import { env } from "cloudflare:test";
import { afterEach, describe, expect, it, vi } from "vitest";
import { call, friend, owner } from "./helpers.js";

const realFetch = globalThis.fetch;
function stub() {
  const mails = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const u = typeof input === "string" ? input : input.url;
    if (u.startsWith("https://challenges.cloudflare.com/")) return Response.json({ success: init.body.get("response") === "good" });
    if (u === "https://api.resend.com/emails") { mails.push(JSON.parse(init.body)); return Response.json({ id: "m1" }); }
    return realFetch(input, init);
  });
  return mails;
}
afterEach(() => vi.restoreAllMocks());

const ip = (n) => ({ "CF-Connecting-IP": `203.0.113.${n}`, "User-Agent": "Mozilla/5.0 (iPhone)" });
const signup = (body, n = 1) => call("POST", "/api/signup", { body: { turnstile_token: "good", ...body }, headers: ip(n) });
const login = (body, n = 1) => call("POST", "/api/login", { body, headers: ip(n) });

describe("username, email and password", () => {
  it("sign up, then log in by username or email on another phone", async () => {
    stub();
    const r = await signup({ username: "robin_k", email: "Robin@Example.com", password: "glassyice1" });
    expect(r.status).toBe(200);
    const a = await r.json();
    expect(a).toMatchObject({ name: "robin_k", role: "friend" });
    expect((await call("GET", "/api/me", { token: a.device_key })).status).toBe(200);
    const row = await env.DB.prepare("SELECT pass_hash, email FROM friends WHERE username = 'robin_k'").first();
    expect(row.email).toBe("robin@example.com");
    expect(row.pass_hash).not.toContain("glassyice1");
    const b = await (await login({ login: "ROBIN@example.com", password: "glassyice1" })).json();
    expect(b.device_key).not.toBe(a.device_key);
    expect((await login({ login: "robin_k", password: "nope-nope" })).status).toBe(401);
  });

  it("rejects taken names and emails, bad input and failed checks", async () => {
    stub();
    await signup({ username: "pat", email: "pat@example.com", password: "password1" });
    expect((await signup({ username: "PAT", email: "x@example.com", password: "password1" }, 2)).status).toBe(409);
    expect((await signup({ username: "pat2", email: "pat@example.com", password: "password1" }, 3)).status).toBe(409);
    expect((await signup({ username: "p", email: "y@example.com", password: "password1" }, 4)).status).toBe(400);
    expect((await signup({ username: "pat3", email: "nope", password: "password1" }, 4)).status).toBe(400);
    expect((await signup({ username: "pat3", email: "z@example.com", password: "short" }, 4)).status).toBe(400);
    expect((await signup({ username: "pat3", email: "z@example.com", password: "password1", turnstile_token: "bad" }, 4)).status).toBe(403);
  });

  it("too many wrong passwords from one place are slowed down", async () => {
    stub();
    await signup({ username: "sam", email: "sam@example.com", password: "password1" }, 5);
    for (let i = 0; i < 10; i++) await login({ login: "sam", password: "wrong-wrong" }, 6);
    expect((await login({ login: "sam", password: "password1" }, 6)).status).toBe(429);
    expect((await login({ login: "sam", password: "password1" }, 7)).status).toBe(200);
  });

  it("an older account adds a login; changing it needs the current password", async () => {
    stub();
    const fk = await friend(await owner(), "Pat");
    expect(await (await call("GET", "/api/me/login", { token: fk })).json()).toMatchObject({ username: null, has_password: false });
    expect((await call("POST", "/api/me/login", { token: fk, body: { username: "patq", email: "patq@example.com", password: "password1" } })).status).toBe(200);
    expect((await login({ login: "patq", password: "password1" })).status).toBe(200);
    expect((await call("POST", "/api/me/login", { token: fk, body: { password: "password2" } })).status).toBe(403);
    expect((await call("POST", "/api/me/login", { token: fk, body: { password: "password2", current_password: "password1" } })).status).toBe(200);
  });

  it("forgot password emails a one-time link (when email is set up); the owner can make one too", async () => {
    const mails = stub();
    const ok = await owner();
    await signup({ username: "lee", email: "lee@example.com", password: "password1" }, 8);
    env.RESEND_API_KEY = "re_test"; env.MAIL_FROM = "Wild Ice <ice@example.com>";
    try {
      expect((await call("POST", "/api/password/forgot", { body: { email: "nobody@example.com" } })).status).toBe(200);
      expect(mails).toHaveLength(0);
      await call("POST", "/api/password/forgot", { body: { email: "LEE@example.com" } });
      expect(mails).toHaveLength(1);
      const token = mails[0].text.match(/#reset=([\w-]+)/)[1];
      const r = await call("POST", "/api/password/reset", { body: { token, password: "newpassword" } });
      expect(r.status).toBe(200);
      expect((await call("POST", "/api/password/reset", { body: { token, password: "another1" } })).status).toBe(410);
      expect((await login({ login: "lee", password: "newpassword" }, 9)).status).toBe(200);
    } finally { delete env.RESEND_API_KEY; delete env.MAIL_FROM; }
    const lee = await env.DB.prepare("SELECT id FROM friends WHERE username = 'lee'").first();
    const link = await (await call("POST", `/api/friends/${lee.id}/reset-link`, { token: ok })).json();
    expect(link.reset_url).toMatch(/#reset=/);
  });
});
