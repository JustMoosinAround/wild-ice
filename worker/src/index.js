// Wild Ice "Ice Log" worker: routing only. See docs/superpowers/specs/2026-11-20-ice-log-design.md.
import { bootstrap, invite, me, redeem, revoke } from "./auth.js";
import { HttpError, json, preflight, withCors } from "./http.js";
import { getExport, getPhoto, postReport } from "./reports.js";
import { postComment } from "./comments.js";
import { getLake } from "./lakes.js";
import { getReview, postPref, reviewComment, reviewPhoto } from "./review.js";
import { scheduled } from "./cron.js";

const ROUTES = [
  ["POST", /^\/api\/bootstrap$/, bootstrap],
  ["POST", /^\/api\/invites\/redeem$/, redeem],
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
  ["POST", /^\/api\/prefs$/, postPref],
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
