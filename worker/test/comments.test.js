import { afterEach, describe, expect, it, vi } from "vitest";
import { call, friend, owner } from "./helpers.js";

const realFetch = globalThis.fetch;
const verifyCalls = [];

// Fake Turnstile siteverify: token "good" passes, anything else fails.
function stubTurnstile() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    if (url.startsWith("https://challenges.cloudflare.com/turnstile/v0/siteverify")) {
      const form = init.body;
      verifyCalls.push(Object.fromEntries(form));
      return new Response(JSON.stringify({ success: form.get("response") === "good" }));
    }
    return realFetch(input, init);
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  verifyCalls.length = 0;
});

const comment = (extra = {}) => ({ lake_id: "w123", name: "Sam", text: "Plowed lot on the east side", turnstile_token: "good", ...extra });
const stranger = (body, ip = "203.0.113.5") =>
  call("POST", "/api/comments", { body, headers: { "CF-Connecting-IP": ip } });
const lake = async (id = "w123") => (await call("GET", `/api/lakes/${id}`)).json();

describe("comments", () => {
  it("stranger comment waits", async () => {
    stubTurnstile();
    const r = await stranger(comment());
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ status: "pending" });
    expect((await lake()).comments).toEqual([]);
    expect(verifyCalls[0]).toMatchObject({ secret: "test-turnstile", response: "good", remoteip: "203.0.113.5" });
  });

  it("friend comment publishes without Turnstile", async () => {
    stubTurnstile();
    const fk = await friend(await owner());
    const r = await call("POST", "/api/comments", { body: comment({ turnstile_token: undefined }), token: fk });
    expect(await r.json()).toEqual({ status: "published" });
    const got = (await lake()).comments;
    expect(got).toHaveLength(1);
    expect(got[0]).toMatchObject({ name: "Sam", text: "Plowed lot on the east side" });
    expect(Object.keys(got[0]).sort()).toEqual(["created_at", "name", "text"]);
    expect(verifyCalls).toHaveLength(0);
  });

  it("links and long text refused", async () => {
    stubTurnstile();
    for (const text of ["see http://x.com", "www.spam.com deals", "go to spam.biz/now", "x".repeat(501), "   "]) {
      const r = await stranger(comment({ text }));
      expect(r.status).toBe(400);
      expect((await r.json()).error).toBeTruthy();
    }
    expect((await stranger(comment({ name: "" }))).status).toBe(400);
    expect((await stranger(comment({ name: "n".repeat(41) }))).status).toBe(400);
    expect((await stranger(comment({ lake_id: "nope" }))).status).toBe(400);
  });

  it("4th stranger comment in an hour → 429", async () => {
    stubTurnstile();
    for (let i = 0; i < 3; i++) expect((await stranger(comment())).status).toBe(200);
    const fourth = await stranger(comment());
    expect(fourth.status).toBe(429);
    expect((await fourth.json()).error).toBe("Too many comments, try again later");
    expect((await stranger(comment(), "198.51.100.9")).status).toBe(200);
  });

  it("failed Turnstile → 403", async () => {
    stubTurnstile();
    expect((await stranger(comment({ turnstile_token: "bad" }))).status).toBe(403);
    expect((await stranger(comment({ turnstile_token: undefined }))).status).toBe(403);
  });

  it("lake comments newest first, published only, max 50", async () => {
    stubTurnstile();
    const fk = await friend(await owner());
    for (let i = 0; i < 52; i++) {
      await call("POST", "/api/comments", { body: comment({ text: `note ${i}` }), token: fk });
    }
    await stranger(comment({ text: "pending one" }));
    const got = (await lake()).comments;
    expect(got).toHaveLength(50);
    expect(got[0].text).toBe("note 51");
    expect(got.some((c) => c.text === "pending one")).toBe(false);
  });
});
