// Public trip reports: what members skated, their story, photo and track time, with kudos.
import { deviceFriend, requireDevice } from "./auth.js";
import { HttpError, json, now } from "./http.js";

const FEED_DAYS = 60;
const FEED_MAX = 50;

// Recent trip reports, newest first; `lakeId` narrows to one lake.
export async function tripReports(env, request, lakeId = null) {
  const who = await deviceFriend(env, request).catch(() => null);
  const since = new Date(Date.now() - FEED_DAYS * 86400_000).toISOString().slice(0, 10);
  const { results } = await env.DB.prepare(
    `SELECT r.id, r.lake_id, r.day, r.rating, r.grade, r.story, r.track_minutes, r.created_at,
            f.name, f.avatar_id AS avatar,
            CASE WHEN p.status IS NOT NULL AND p.status != 'rejected' THEN p.public_id END AS photo,
            (SELECT COUNT(*) FROM kudos k WHERE k.report_id = r.id) AS kudos,
            (SELECT COUNT(*) FROM kudos k WHERE k.report_id = r.id AND k.friend_id = ?) AS mine
     FROM reports r JOIN friends f ON f.id = r.friend_id
     LEFT JOIN photos p ON p.id = r.photo_id
     WHERE r.day >= ? AND f.revoked_at IS NULL AND (? IS NULL OR r.lake_id = ?)
     ORDER BY r.day DESC, r.created_at DESC LIMIT ?`,
  ).bind(who?.id ?? "", since, lakeId, lakeId, FEED_MAX).all();
  return results.map((r) => ({ ...r, mine: undefined, gave_kudos: r.mine > 0 }));
}

export async function getFeed(env, request) {
  return json({ reports: await tripReports(env, request) });
}

// Members give (or take back) kudos on a trip report.
export async function postKudos(env, request, reportId) {
  const who = await requireDevice(env, request);
  const r = await env.DB.prepare("SELECT id FROM reports WHERE id = ?").bind(reportId).first();
  if (!r) throw new HttpError(404, "No such report");
  const had = await env.DB.prepare("DELETE FROM kudos WHERE report_id = ? AND friend_id = ?")
    .bind(reportId, who.id).run();
  if (had.meta.changes === 0) {
    await env.DB.prepare("INSERT INTO kudos (report_id, friend_id, created_at) VALUES (?, ?, ?)")
      .bind(reportId, who.id, now()).run();
  }
  const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM kudos WHERE report_id = ?").bind(reportId).first("n");
  return json({ kudos: n, gave_kudos: had.meta.changes === 0 });
}
