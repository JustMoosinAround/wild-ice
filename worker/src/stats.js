// Anonymous usage counts: installed copies of the app and a few daily tallies.
import { requireOwner } from "./auth.js";
import { HttpError, json, now, readJson } from "./http.js";

const PLATFORMS = new Set(["ios", "android", "desktop", "other"]);
const TALLIES = new Set(["get_app_click", "app_open"]);

// The installed app says hello once a day: {id, platform}. The id is random, made by the app.
export async function ping(env, request) {
  const body = await readJson(request);
  if (typeof body.id !== "string" || !/^[\w-]{16,64}$/.test(body.id)) throw new HttpError(400, "Bad id");
  const platform = PLATFORMS.has(body.platform) ? body.platform : "other";
  const t = now();
  await env.DB.prepare(
    `INSERT INTO installs (id, platform, first_seen, last_seen) VALUES (?, ?, ?, ?)
     ON CONFLICT(id) DO UPDATE SET last_seen = excluded.last_seen, platform = excluded.platform`,
  ).bind(body.id, platform, t, t).run();
  return json({ ok: true });
}

// +1 to a named daily tally (only known names).
export async function tally(env, request) {
  const body = await readJson(request);
  if (!TALLIES.has(body.name)) throw new HttpError(400, "Unknown tally");
  await env.DB.prepare(
    `INSERT INTO tallies (day, name, n) VALUES (?, ?, 1)
     ON CONFLICT(day, name) DO UPDATE SET n = n + 1`,
  ).bind(now().slice(0, 10), body.name).run();
  return json({ ok: true });
}

export async function getStats(env, request) {
  await requireOwner(env, request);
  const day = (n) => new Date(Date.now() - n * 86400_000).toISOString();
  const one = (sql, ...args) => env.DB.prepare(sql).bind(...args).first("n");
  const byPlatform = (await env.DB.prepare(
    "SELECT platform, COUNT(*) AS n FROM installs GROUP BY platform ORDER BY n DESC").all()).results;
  const tallySince = (name, n) => one("SELECT COALESCE(SUM(n), 0) AS n FROM tallies WHERE name = ? AND day >= ?",
    name, day(n).slice(0, 10));
  return json({
    installs: {
      total: await one("SELECT COUNT(*) AS n FROM installs"),
      new_7d: await one("SELECT COUNT(*) AS n FROM installs WHERE first_seen > ?", day(7)),
      active_7d: await one("SELECT COUNT(*) AS n FROM installs WHERE last_seen > ?", day(7)),
      active_30d: await one("SELECT COUNT(*) AS n FROM installs WHERE last_seen > ?", day(30)),
      by_platform: Object.fromEntries(byPlatform.map((r) => [r.platform, r.n])),
    },
    members: {
      total: await one("SELECT COUNT(*) AS n FROM friends WHERE revoked_at IS NULL"),
      new_7d: await one("SELECT COUNT(*) AS n FROM friends WHERE revoked_at IS NULL AND created_at > ?", day(7)),
    },
    get_app_clicks: { d7: await tallySince("get_app_click", 7), d30: await tallySince("get_app_click", 30) },
    reports_30d: await one("SELECT COUNT(*) AS n FROM reports WHERE created_at > ?", day(30)),
  });
}
