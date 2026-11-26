// Wild Ice "Ice Log" worker: routing only. See docs/superpowers/specs/2026-11-20-ice-log-design.md.
import { bootstrap, invite, join, me, redeem, revoke } from "./auth.js";
import { HttpError, json, preflight, withCors } from "./http.js";
import { getExport, getPhoto, postReport } from "./reports.js";
import { postComment } from "./comments.js";
import { getLake } from "./lakes.js";
import { getReview, postPref, reviewComment, reviewPhoto, reviewReport } from "./review.js";
import { scheduled } from "./cron.js";
import { getStats, ping, tally } from "./stats.js";
import { getFeed, postKudos } from "./feed.js";
import { deleteSaved, getSaved, getSkated, postSaved } from "./saved.js";
import { deleteMe, deleteMyDevice, deleteReport, getAvatar, myDevices, myExport, myInvite, myReports,
  postMyPhoto, putMe } from "./account.js";

const ROUTES = [
  ["POST", /^\/api\/bootstrap$/, bootstrap],
  ["POST", /^\/api\/invites\/redeem$/, redeem],
  ["POST", /^\/api\/join$/, join],
  ["POST", /^\/api\/ping$/, ping],
  ["POST", /^\/api\/tally$/, tally],
  ["GET", /^\/api\/stats$/, getStats],
  ["GET", /^\/api\/feed$/, getFeed],
  ["POST", /^\/api\/reports\/([\w-]+)\/kudos$/, postKudos],
  ["GET", /^\/api\/me$/, me],
  ["POST", /^\/api\/invites$/, invite],
  ["POST", /^\/api\/friends\/([\w-]+)\/revoke$/, revoke],
  ["POST", /^\/api\/reports$/, postReport],
  ["GET", /^\/api\/photos\/([\w-]+)$/, getPhoto],
  ["GET", /^\/api\/export$/, getExport],
  ["POST", /^\/api\/comments$/, postComment],
  ["GET", /^\/api\/lakes\/([\w-]+)$/, getLake],
  ["GET", /^\/api\/review$/, getReview],
  ["POST", /^\/api\/review\/comments\/([\w-]+)$/, reviewComment],
  ["POST", /^\/api\/review\/photos\/([\w-]+)$/, reviewPhoto],
  ["POST", /^\/api\/review\/reports\/([\w-]+)$/, reviewReport],
  ["POST", /^\/api\/prefs$/, postPref],
  ["GET", /^\/api\/saved$/, getSaved],
  ["POST", /^\/api\/saved$/, postSaved],
  ["DELETE", /^\/api\/saved\/([\w-]+)$/, deleteSaved],
  ["GET", /^\/api\/me\/skated$/, getSkated],
  ["PUT", /^\/api\/me$/, putMe],
  ["POST", /^\/api\/me\/photo$/, postMyPhoto],
  ["GET", /^\/api\/avatars\/([\w-]+)$/, getAvatar],
  ["GET", /^\/api\/me\/reports$/, myReports],
  ["DELETE", /^\/api\/reports\/([\w-]+)$/, deleteReport],
  ["GET", /^\/api\/me\/devices$/, myDevices],
  ["DELETE", /^\/api\/me\/devices\/([\w-]+)$/, deleteMyDevice],
  ["POST", /^\/api\/me\/invite$/, myInvite],
  ["GET", /^\/api\/me\/export$/, myExport],
  ["POST", /^\/api\/me\/delete$/, deleteMe],
];

async function route(request, env, ctx) {
  const { pathname } = new URL(request.url);
  for (const [method, pattern, handler] of ROUTES) {
    const m = pathname.match(pattern);
    if (m && request.method === method) return handler(env, request, ...m.slice(1), ctx);
  }
  throw new HttpError(404, "Not found");
}

export default {
  scheduled,
  async fetch(request, env, ctx) {
    if (request.method === "OPTIONS") return preflight(request, env);
    let response;
    try {
      response = await route(request, env, ctx);
    } catch (err) {
      if (err instanceof HttpError) response = json({ error: err.message }, err.status);
      else {
        console.error("unhandled", err && err.stack);
        response = json({ error: "Something went wrong" }, 500);
      }
    }
    return withCors(response, request, env);
  },
};
