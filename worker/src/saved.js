// Saved lakes ("My lakes") and the lakes this friend has skated.
import { requireDevice } from "./auth.js";
import { HttpError, json, now, readJson } from "./http.js";

const LAKE_ID = /^[wr]\d{1,12}$/;

function lakeId(id) {
  if (typeof id !== "string" || !LAKE_ID.test(id)) throw new HttpError(400, "Unknown lake");
  return id;
}

export async function getSaved(env, request) {
  const who = await requireDevice(env, request);
  const { results } = await env.DB.prepare(
    "SELECT lake_id FROM saved WHERE friend_id = ? ORDER BY created_at").bind(who.id).all();
  return json({ lakes: results.map((r) => r.lake_id) });
}

export async function postSaved(env, request) {
  const who = await requireDevice(env, request);
  const id = lakeId((await readJson(request)).lake_id);
  await env.DB.prepare(
    "INSERT OR IGNORE INTO saved (friend_id, lake_id, created_at) VALUES (?, ?, ?)",
  ).bind(who.id, id, now()).run();
  return json({ ok: true });
}

export async function deleteSaved(env, request, id) {
  const who = await requireDevice(env, request);
  await env.DB.prepare("DELETE FROM saved WHERE friend_id = ? AND lake_id = ?")
    .bind(who.id, lakeId(id)).run();
  return json({ ok: true });
}

export async function getSkated(env, request) {
  const who = await requireDevice(env, request);
  const { results } = await env.DB.prepare(
    `SELECT lake_id, MAX(day) AS day FROM reports
     WHERE friend_id = ? AND rating IN ('skated', 'rough') GROUP BY lake_id ORDER BY day DESC`,
  ).bind(who.id).all();
  return json({ lakes: results });
}
