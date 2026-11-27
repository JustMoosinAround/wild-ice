// A Strava or Garmin Connect activity link (pasted or shared from the app) -> the
// service's own GPX download for it. No API: the person's browser, signed in to the
// service, downloads their own file, and Wild Ice reads it like any upload.

const STRAVA = /strava\.com\/activities\/(\d{5,15})/i;
const GARMIN = /connect\.garmin\.com\/(?:modern|app)\/activity\/(\d{5,15})/i;
const SHORT = /https:\/\/(?:strava\.app\.link|www\.strava\.com\/s|connect\.garmin\.com\/s|gcn\.garmin\.com)\/[\w\-/?=&.%]+/i;

// {service, id, gpxUrl, pageUrl} | {short: url} (a short link the worker resolves) | null
export function parseActivityLink(text) {
  const t = String(text || "");
  let m = t.match(STRAVA);
  if (m) {
    return { service: "Strava", id: m[1], pageUrl: `https://www.strava.com/activities/${m[1]}`,
      gpxUrl: `https://www.strava.com/activities/${m[1]}/export_gpx` };
  }
  m = t.match(GARMIN);
  if (m) {
    return { service: "Garmin Connect", id: m[1], pageUrl: `https://connect.garmin.com/modern/activity/${m[1]}`,
      gpxUrl: `https://connect.garmin.com/modern/proxy/download-service/export/gpx/activity/${m[1]}` };
  }
  m = t.match(SHORT);
  return m ? { short: m[0] } : null;
}

// What an Android "Share -> Wild Ice" put in the address (title, text and url params).
export function sharedText(search) {
  const q = new URLSearchParams(search || "");
  return ["share_url", "share_text", "share_title"].map((k) => q.get(k)).filter(Boolean).join(" ");
}

// On Android the Strava / Garmin apps grab their websites' links (and their apps can't
// export a GPX). An intent link makes Chrome open it instead, so the download happens.
export function browserHref(url, userAgent) {
  if (!/Android/i.test(userAgent || "")) return url;
  const u = new URL(url);
  return `intent://${u.host}${u.pathname}${u.search}#Intent;scheme=https;package=com.android.chrome;`
    + `S.browser_fallback_url=${encodeURIComponent(url)};end`;
}
