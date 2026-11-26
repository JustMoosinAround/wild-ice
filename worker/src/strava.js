// Connect Strava: a member links their Strava account once, then picks a recent skate
// to log, with no file to download. Strava's terms allow showing a member's Strava data
// only to that member, so: activities and points pass straight through to their phone
// (never stored), and reports made from them never show their track details to others.
import { requireDevice } from "./auth.js";
import { HttpError, json, now, readJson } from "./http.js";

const API = "https://www.strava.com/api/v3";
const TOKEN_URL = "https://www.strava.com/oauth/token";
const LIST_DAYS = 60;

function configured(env) {
  if (!env.STRAVA_CLIENT_ID || !env.STRAVA_CLIENT_SECRET) throw new HttpError(503, "Strava isn't set up yet");
}

async function tokenCall(env, params) {
  const res = await fetch(TOKEN_URL, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: env.STRAVA_CLIENT_ID, client_secret: env.STRAVA_CLIENT_SECRET, ...params }) });
  if (!res.ok) throw new HttpError(res.status === 400 || res.status === 401 ? 400 : 502, "Strava didn't accept that, try connecting again");
  return res.json();
}

export async function stravaConnect(env, request) {
  configured(env);
  const who = await requireDevice(env, request);
  const { code, scope } = await readJson(request);
  if (typeof code !== "string" || !code) throw new HttpError(400, "Missing code");
  if (typeof scope === "string" && !scope.includes("activity:read")) {
    throw new HttpError(400, "Wild Ice needs permission to read your activities: connect again and leave that box ticked");
  }
  const t = await tokenCall(env, { code, grant_type: "authorization_code" });
  const a = t.athlete || {};
  await env.DB.prepare(
    `INSERT INTO strava (friend_id, athlete_id, athlete_name, access_token, refresh_token, expires_at, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(friend_id) DO UPDATE SET athlete_id = excluded.athlete_id, athlete_name = excluded.athlete_name,
       access_token = excluded.access_token, refresh_token = excluded.refresh_token, expires_at = excluded.expires_at`,
  ).bind(who.id, String(a.id ?? ""), [a.firstname, a.lastname].filter(Boolean).join(" ") || null,
    t.access_token, t.refresh_token, t.expires_at, now()).run();
  return json({ connected: true, athlete: a.firstname || null });
}

async function accessToken(env, who) {
  const row = await env.DB.prepare("SELECT * FROM strava WHERE friend_id = ?").bind(who.id).first();
  if (!row) throw new HttpError(404, "Strava isn't connected");
  if (row.expires_at > Date.now() / 1000 + 120) return row.access_token;
  configured(env);
  const t = await tokenCall(env, { grant_type: "refresh_token", refresh_token: row.refresh_token });
  await env.DB.prepare("UPDATE strava SET access_token = ?, refresh_token = ?, expires_at = ? WHERE friend_id = ?")
    .bind(t.access_token, t.refresh_token, t.expires_at, who.id).run();
  return t.access_token;
}

async function stravaGet(env, who, path) {
  const res = await fetch(API + path, { headers: { Authorization: `Bearer ${await accessToken(env, who)}` } });
  if (res.status === 401) throw new HttpError(401, "Strava access ended: connect again");
  if (res.status === 429) throw new HttpError(429, "Strava is busy, try again in a few minutes");
  if (!res.ok) throw new HttpError(502, "Strava didn't answer, try again");
  return res.json();
}

export async function stravaStatus(env, request) {
  const who = await requireDevice(env, request);
  const row = await env.DB.prepare("SELECT athlete_name FROM strava WHERE friend_id = ?").bind(who.id).first();
  return json({ available: Boolean(env.STRAVA_CLIENT_ID && env.STRAVA_CLIENT_SECRET), connected: Boolean(row),
    athlete: row?.athlete_name || null });
}

// The member's recent activities with a GPS track, skates first.
export async function stravaActivities(env, request) {
  const who = await requireDevice(env, request);
  const after = Math.floor(Date.now() / 1000) - LIST_DAYS * 86400;
  const list = await stravaGet(env, who, `/athlete/activities?after=${after}&per_page=60`);
  const out = (Array.isArray(list) ? list : []).filter((a) => a.start_latlng && a.start_latlng.length === 2)
    .map((a) => ({ id: String(a.id), name: a.name, type: a.sport_type || a.type, start: a.start_date,
      minutes: Math.round((a.moving_time || 0) / 60) }));
  out.sort((a, b) => Number(b.type === "IceSkate") - Number(a.type === "IceSkate") || String(b.start).localeCompare(String(a.start)));
  return json({ activities: out });
}

// One activity's points ({lat, lon, t} with t in ms), for the member's phone to match.
export async function stravaPoints(env, request, id) {
  const who = await requireDevice(env, request);
  const act = await stravaGet(env, who, `/activities/${id}`);
  const streams = await stravaGet(env, who, `/activities/${id}/streams?keys=latlng,time&key_by_type=true`);
  const ll = streams.latlng?.data || [], tt = streams.time?.data || [];
  const t0 = Date.parse(act.start_date);
  const points = ll.map(([lat, lon], i) => ({ lat, lon, t: t0 + (tt[i] ?? 0) * 1000 }));
  return json({ name: act.name, points });
}

export async function stravaDisconnect(env, request) {
  const who = await requireDevice(env, request);
  const row = await env.DB.prepare("SELECT access_token FROM strava WHERE friend_id = ?").bind(who.id).first();
  if (row) {
    await fetch("https://www.strava.com/oauth/deauthorize", { method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: `access_token=${encodeURIComponent(row.access_token)}` })
      .catch(() => {});
    await env.DB.prepare("DELETE FROM strava WHERE friend_id = ?").bind(who.id).run();
  }
  return json({ connected: false });
}
