import { afterEach, describe, expect, it, vi } from "vitest";
import { call } from "./helpers.js";

const realFetch = globalThis.fetch;
function stubTurnstile() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    if (url.startsWith("https://challenges.cloudflare.com/turnstile/v0/siteverify")) {
      return new Response(JSON.stringify({ success: init.body.get("response") === "good" }));
    }
    return realFetch(input, init);
  });
}
afterEach(() => vi.restoreAllMocks());

const join = (body, ip = "203.0.113.9") =>
  call("POST", "/api/join", { body, headers: { "CF-Connecting-IP": ip, "User-Agent": "Mozilla/5.0 (iPhone)" } });

describe("open sign-up", () => {
  it("a name and a passed check make an account that can post", async () => {
    stubTurnstile();
    const r = await join({ name: "  Robin  ", turnstile_token: "good" });
    expect(r.status).toBe(200);
    const d = await r.json();
    expect(d).toMatchObject({ name: "Robin", role: "friend" });
    const me = await call("GET", "/api/me", { token: d.device_key });
    expect((await me.json()).name).toBe("Robin");
    const rep = await call("POST", "/api/reports", { body: { idem_key: crypto.randomUUID(), lake_id: "w1", rating: "skated" }, token: d.device_key });
    expect(rep.status).toBe(200);
  });

  it("needs a name and the check", async () => {
    stubTurnstile();
    expect((await join({ name: "", turnstile_token: "good" })).status).toBe(400);
    expect((await join({ name: "Robin", turnstile_token: "bad" })).status).toBe(403);
    expect((await join({ name: "Robin" })).status).toBe(403);
  });

  it("at most 3 sign-ups a day from one connection", async () => {
    stubTurnstile();
    for (let i = 0; i < 3; i++) expect((await join({ name: "R" + i, turnstile_token: "good" }, "198.51.100.1")).status).toBe(200);
    expect((await join({ name: "R4", turnstile_token: "good" }, "198.51.100.1")).status).toBe(429);
    expect((await join({ name: "Other", turnstile_token: "good" }, "198.51.100.2")).status).toBe(200);
  });
});
