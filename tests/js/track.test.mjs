import { test } from "node:test";
import assert from "node:assert/strict";
import { TrackError, matchLakes, parseFit, parseGpx, readTrackFile } from "../../site/track.js";

const SQUARE = (id, lat0, lon0) => ({ type: "Feature", properties: { id, name: `Lake ${id}` },
  geometry: { type: "Polygon", coordinates: [[[lon0, lat0], [lon0 + 0.02, lat0], [lon0 + 0.02, lat0 + 0.01],
    [lon0, lat0 + 0.01], [lon0, lat0]]] } });
const A = SQUARE("w1", 61.0, -149.5);
const B = SQUARE("w2", 61.1, -149.5);
const START = Date.parse("2026-01-03T08:30:00Z"); // Jan 2, 23:30 in Alaska

function pts(n, lat, lon, t0 = START, step = 60000) {
  return Array.from({ length: n }, (_, i) => ({ lat: lat + i * 1e-5, lon: lon + i * 1e-5, t: t0 + i * step }));
}

function gpx(points, withTime = true) {
  const tp = points.map((p) => `<trkpt lat="${p.lat}" lon="${p.lon}">${withTime ? `<time>${new Date(p.t).toISOString()}</time>` : ""}</trkpt>`).join("");
  return `<?xml version="1.0"?><gpx><trk><trkseg>${tp}</trkseg></trk></gpx>`;
}

function fit(points) {
  const SEMI = 2 ** 31 / 180;
  const recs = [];
  recs.push(Uint8Array.from([0x40, 0, 0, 20, 0, 3, 253, 4, 0x86, 0, 4, 0x85, 1, 4, 0x85]));
  for (const p of points) {
    const b = new DataView(new ArrayBuffer(13));
    b.setUint8(0, 0x00);
    b.setUint32(1, Math.round(p.t / 1000) - 631065600, true);
    b.setInt32(5, Math.round(p.lat * SEMI), true);
    b.setInt32(9, Math.round(p.lon * SEMI), true);
    recs.push(new Uint8Array(b.buffer));
  }
  const size = recs.reduce((n, r) => n + r.length, 0);
  const out = new Uint8Array(14 + size + 2);
  const h = new DataView(out.buffer);
  h.setUint8(0, 14); h.setUint8(1, 0x10); h.setUint32(4, size, true);
  out.set([0x2e, 0x46, 0x49, 0x54], 8);
  let o = 14;
  for (const r of recs) { out.set(r, o); o += r.length; }
  return out.buffer;
}

test("GPX on one lake: minutes, Alaska day across UTC midnight, a point on the lake", () => {
  const m = matchLakes(parseGpx(gpx(pts(30, 61.004, -149.49))), [A, B]);
  assert.equal(m.length, 1);
  assert.equal(m[0].lakeId, "w1");
  assert.equal(m[0].minutes, 29);
  assert.equal(m[0].day, "2026-01-02");
  assert.ok(Math.abs(m[0].point.lat - 61.004) < 0.001);
});

test("FIT gives the same points as GPX", () => {
  const p = pts(30, 61.004, -149.49);
  const got = parseFit(fit(p));
  assert.equal(got.length, 30);
  assert.ok(Math.abs(got[5].lat - p[5].lat) < 1e-6 && Math.abs(got[5].lon - p[5].lon) < 1e-6);
  assert.equal(got[5].t, p[5].t);
  assert.equal(matchLakes(got, [A])[0].minutes, 29);
});

test("a track over two lakes lists both, most time first", () => {
  const p = [...pts(20, 61.004, -149.49), ...pts(40, 61.104, -149.49, START + 20 * 60000)];
  const m = matchLakes(p, [A, B]);
  assert.deepEqual(m.map((x) => x.lakeId), ["w2", "w1"]);
});

test("no lake, too short, and gaps don't count", () => {
  assert.deepEqual(matchLakes(pts(30, 62.5, -150), [A, B]), []);
  assert.deepEqual(matchLakes(pts(8, 61.004, -149.49), [A]), []);
  const gappy = pts(30, 61.004, -149.49, START, 400000); // 400 s steps: all gaps
  assert.deepEqual(matchLakes(gappy, [A]), []);
});

test("a GPX without times and a broken .gz give readable errors", async () => {
  assert.throws(() => parseGpx(gpx(pts(5, 61, -149), false)), (e) => e instanceof TrackError && e.message === "This track has no times");
  const bad = new File([new Uint8Array([1, 2, 3, 4])], "x.fit.gz");
  await assert.rejects(readTrackFile(bad), (e) => e instanceof TrackError && e.message === "Couldn't read this file");
  const good = new File([gpx(pts(3, 61, -149))], "ride.gpx");
  assert.equal((await readTrackFile(good)).length, 3);
});
