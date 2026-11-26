import { afterEach, describe, expect, it, vi } from "vitest";
import { call } from "./helpers.js";

afterEach(() => vi.restoreAllMocks());

describe("short activity links", () => {
  it("follows a strava.app.link redirect to the activity", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const u = typeof input === "string" ? input : input.url;
      if (u.startsWith("https://strava.app.link/")) return new Response("", { status: 307, headers: { Location: "https://www.strava.com/activities/16543210987?share_sig=x" } });
      throw new Error("unexpected " + u);
    });
    const r = await call("GET", "/api/resolve-link?url=" + encodeURIComponent("https://strava.app.link/AbCd123"));
    expect(await r.json()).toEqual({ url: "https://www.strava.com/activities/16543210987" });
  });

  it("only Strava and Garmin hosts", async () => {
    expect((await call("GET", "/api/resolve-link?url=" + encodeURIComponent("https://evil.example/x"))).status).toBe(400);
  });
});
