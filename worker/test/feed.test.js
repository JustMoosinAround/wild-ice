import { describe, expect, it } from "vitest";
import { call, friend, owner } from "./helpers.js";

const JPEG = btoa(String.fromCharCode(0xff, 0xd8, 0xff, 0xe0, ...new Array(200).fill(7)));
const report = (extra = {}) => ({ idem_key: crypto.randomUUID(), lake_id: "w123", rating: "skated", grade: "A", ...extra });

describe("trip reports", () => {
  it("story, photo and kudos show in the public feed and on the lake; notes stay private", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    const r = await (await call("POST", "/api/reports", {
      body: report({ story: "Glassy from the boat launch to the island.", note: "secret spot", photo: JPEG }), token: fk })).json();
    const feed = (await (await call("GET", "/api/feed")).json()).reports;
    expect(feed).toHaveLength(1);
    expect(feed[0]).toMatchObject({ id: r.id, name: "Pat", story: "Glassy from the boat launch to the island.", kudos: 0 });
    expect(feed[0].note).toBeUndefined();
    expect((await call("GET", `/api/photos/${feed[0].photo}`)).status).toBe(200); // public at once
    const k = await (await call("POST", `/api/reports/${r.id}/kudos`, { token: ok })).json();
    expect(k).toEqual({ kudos: 1, gave_kudos: true });
    const mine = (await (await call("GET", "/api/feed", { token: ok })).json()).reports[0];
    expect(mine).toMatchObject({ kudos: 1, gave_kudos: true });
    expect(await (await call("POST", `/api/reports/${r.id}/kudos`, { token: ok })).json()).toEqual({ kudos: 0, gave_kudos: false });
    expect((await call("POST", `/api/reports/${r.id}/kudos`)).status).toBe(401);
    const lake = await (await call("GET", "/api/lakes/w123")).json();
    expect(lake.reports.map((x) => x.id)).toEqual([r.id]);
  });

  it("no links in stories", async () => {
    const fk = await friend(await owner(), "Pat");
    expect((await call("POST", "/api/reports", { body: report({ story: "see www.spam.com/x" }), token: fk })).status).toBe(400);
  });
});
