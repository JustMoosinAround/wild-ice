import { describe, expect, it } from "vitest";
import { call, friend, owner } from "./helpers.js";

// Potter Marsh, from the owner's Nov 25 track.
const marsh = { name: "Potter Marsh", kind: "marsh", lat: 61.0583, lon: -149.8025, bbox: [-149.8067, 61.0555, -149.7984, 61.0613] };

describe("spots", () => {
  it("a member adds a spot from a track; the same place again is the same spot; reports colour it", async () => {
    const ok = await owner();
    const fk = await friend(ok, "Pat");
    expect((await call("POST", "/api/spots", { body: marsh })).status).toBe(401);
    const a = await (await call("POST", "/api/spots", { body: marsh, token: fk })).json();
    expect(a).toMatchObject({ name: "Potter Marsh", kind: "marsh", existing: false });
    expect(a.id).toMatch(/^s[0-9a-f]{12}$/);
    const again = await (await call("POST", "/api/spots", { body: { ...marsh, name: "The marsh", lat: 61.0590 }, token: ok })).json();
    expect(again).toMatchObject({ id: a.id, name: "Potter Marsh", existing: true });
    const rep = await call("POST", "/api/reports", { token: fk, body: {
      idem_key: crypto.randomUUID(), lake_id: a.id, rating: "skated", grade: "B", story: "Skated the channels.",
      track_minutes: 48, gps: { lat: 61.0583, lon: -149.8025, source: "device" } } });
    expect(rep.status).toBe(200);
    const list = (await (await call("GET", "/api/spots")).json()).spots;
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ id: a.id, added_by: "Pat", last_report: { rating: "skated", grade: "B" } });
    expect((await call("GET", `/api/lakes/${a.id}`)).status).toBe(200);
    expect((await call("POST", `/api/spots/${a.id}/hide`, { token: fk })).status).toBe(403);
    expect((await call("POST", `/api/spots/${a.id}/hide`, { token: ok })).status).toBe(200);
    expect((await (await call("GET", "/api/spots")).json()).spots).toEqual([]);
  });

  it("checks name, kind and box", async () => {
    const fk = await friend(await owner(), "Pat");
    for (const bad of [{ name: "" }, { kind: "ocean" }, { bbox: [-150, 61, -149, 62] }, { lat: 70 }]) {
      expect((await call("POST", "/api/spots", { body: { ...marsh, ...bad }, token: fk })).status).toBe(400);
    }
  });
});
