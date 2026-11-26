// Public view of one lake's Ice Log: published comments and featured photos.
import { lakeComments } from "./comments.js";
import { HttpError, json, PLACE_ID } from "./http.js";
import { featuredPhotos } from "./review.js";
import { tripReports } from "./feed.js";

export async function getLake(env, request, lakeId) {
  if (!PLACE_ID.test(lakeId)) throw new HttpError(404, "Unknown lake");
  return json({ comments: await lakeComments(env, lakeId), photos: await featuredPhotos(env, lakeId),
    reports: await tripReports(env, request, lakeId) });
}
