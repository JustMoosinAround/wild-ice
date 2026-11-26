import { env } from "cloudflare:test";
import { afterEach, describe, expect, it, vi } from "vitest";
import { call, friend, owner } from "./helpers.js";

afterEach(() => vi.restoreAllMocks());

function stubStrava() {
  const seen = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const u = typeof input === "string" ? input : input.url;
    seen.push(u);
    if (u === "https://www.strava.com/oauth/token") {
      const b = JSON.parse(init.body);
      if (b.code === "bad") return new Response("{}", { status: 400 });
      return Response.json({ access_token: "acc", refresh_token: "ref", expires_at: Math.floor(Date.now() / 1000) + 3600,
        athlete: { id: 42, firstname: "Pat", lastname: "Q" } });
    }
    if (u.startsWith("https://www.strava.com/api/v3/athlete/activities")) {
      return Response.json([
        { id: 1, name: "Morning Run", sport_type: "Run", start_date: "2026-11-24T18:00:00Z", moving_time: 1800, start_latlng: [61, -149] },
        { id: 2, name: "Afternoon Skate", sport_type: "IceSkate", start_date: "2026-11-23T22:25:00Z", moving_time: 2900, start_latlng: [61.05, -149.8] },
        { id: 3, name: "Treadmill", sport_type: "Run", start_date: "2026-11-22T18:00:00Z", moving_time: 1800, start_latlng: [] }]);
    }
    if (u === "https://www.strava.com/api/v3/activities/2") return Response.json({ name: "Afternoon Skate", start_date: "2026-11-23T22:25:00Z" });
    if (u.startsWith("https://www.strava.com/api/v3/activities/2/streams")) {
      return Response.json({ latlng: { data: [[61.05, -149.80], [61.051, -149.801]] }, time: { data: [0, 60] } });
    }
    if (u === "https://www.strava.com/oauth/deauthorize") return new Response("{}");
    throw new Error("unexpected " + u);
  });
  return seen;
}

describe("Connect Strava", () => {
  it("connects, lists skates first, passes points through, and disconnects", async () => {
    stubStrava();
    const fk = await friend(await owner(), "Pat");
    expect(await (await call("GET", "/api/strava", { token: fk })).json()).toMatchObject({ available: true, connected: false });
    expect((await call("POST", "/api/strava/connect", { body: { code: "bad" }, token: fk })).status).toBe(400);
    expect((await call("POST", "/api/strava/connect", { body: { code: "c", scope: "read" }, token: fk })).status).toBe(400);
    const c = await call("POST", "/api/strava/connect", { body: { code: "good", scope: "read,activity:read_all" }, token: fk });
    expect(await c.json()).toEqual({ connected: true, athlete: "Pat" });
    const acts = (await (await call("GET", "/api/strava/activities", { token: fk })).json()).activities;
    expect(acts.map((a) => a.id)).toEqual(["2", "1"]); // skate first, no-GPS treadmill dropped
    const pts = await (await call("GET", "/api/strava/activities/2/points", { token: fk })).json();
    expect(pts.points).toEqual([{ lat: 61.05, lon: -149.8, t: Date.parse("2026-11-23T22:25:00Z") },
      { lat: 61.051, lon: -149.801, t: Date.parse("2026-11-23T22:26:00Z") }]);
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM strava").first()).n).toBe(1);
    await call("DELETE", "/api/strava", { token: fk });
    expect((await env.DB.prepare("SELECT COUNT(*) AS n FROM strava").first()).n).toBe(0);
  });

  it("a report from Strava hides its minutes from everyone else", async () => {
    stubStrava();
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    await call("POST", "/api/reports", { token: fk, body: { idem_key: crypto.randomUUID(), lake_id: "w123", rating: "skated",
      track_minutes: 48, gps: { lat: 61.05, lon: -149.8, source: "device" }, via: "strava", story: "Great ice" } });
    const mine = (await (await call("GET", "/api/feed", { token: fk })).json()).reports[0];
    const theirs = (await (await call("GET", "/api/feed", { token: ok })).json()).reports[0];
    const anon = (await (await call("GET", "/api/feed")).json()).reports[0];
    expect(mine.track_minutes).toBe(48);
    expect(theirs.track_minutes).toBeNull();
    expect(anon).toMatchObject({ track_minutes: null, story: "Great ice" });
  });
});
