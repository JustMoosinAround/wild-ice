import { describe, expect, it } from "vitest";
import { call, friend, owner } from "./helpers.js";

describe("usage counts", () => {
  it("counts installed copies once each, tallies taps, and only the owner can read them", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    const id = "a".repeat(24);
    expect((await call("POST", "/api/ping", { body: { id, platform: "ios" } })).status).toBe(200);
    expect((await call("POST", "/api/ping", { body: { id, platform: "ios" } })).status).toBe(200);
    await call("POST", "/api/ping", { body: { id: "b".repeat(24), platform: "android" } });
    expect((await call("POST", "/api/ping", { body: { id: "short" } })).status).toBe(400);
    await call("POST", "/api/tally", { body: { name: "get_app_click" } });
    await call("POST", "/api/tally", { body: { name: "get_app_click" } });
    expect((await call("POST", "/api/tally", { body: { name: "nope" } })).status).toBe(400);
    expect((await call("GET", "/api/stats", { token: fk })).status).toBe(403);
    const s = await (await call("GET", "/api/stats", { token: ok })).json();
    expect(s.installs).toMatchObject({ total: 2, new_7d: 2, active_7d: 2, by_platform: { ios: 1, android: 1 } });
    expect(s.get_app_clicks).toEqual({ d7: 2, d30: 2 });
    expect(s.members.total).toBe(2);
  });
});
