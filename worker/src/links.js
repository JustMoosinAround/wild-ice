// Unwrap a short activity link (Strava's strava.app.link, Garmin's short links) to the
// activity's own address, so the app can offer the GPX download. Only these hosts.
import { HttpError, json } from "./http.js";

const SHORT_HOSTS = new Set(["strava.app.link", "www.strava.com", "strava.com", "connect.garmin.com", "gcn.garmin.com"]);
const ACTIVITY = /https:\/\/(?:www\.)?(?:strava\.com\/activities\/\d{5,15}|connect\.garmin\.com\/(?:modern|app)\/activity\/\d{5,15})/i;

export async function resolveLink(env, request) {
  const raw = new URL(request.url).searchParams.get("url") || "";
  let url;
  try { url = new URL(raw); } catch { throw new HttpError(400, "Not a link"); }
  for (let hop = 0; hop < 5; hop++) {
    if (url.protocol !== "https:" || !SHORT_HOSTS.has(url.hostname)) throw new HttpError(400, "Not a Strava or Garmin link");
    const hit = url.href.match(ACTIVITY);
    if (hit) return json({ url: hit[0] });
    const res = await fetch(url.href, { redirect: "manual", headers: { "User-Agent": "Mozilla/5.0 (WildIce link check)" } });
    const next = res.headers.get("Location");
    if (next) { url = new URL(next, url); continue; }
    const page = (await res.text()).slice(0, 200_000);
    const inPage = page.match(ACTIVITY);
    if (inPage) return json({ url: inPage[0] });
    break;
  }
  throw new HttpError(404, "Couldn't find the activity behind that link");
}
