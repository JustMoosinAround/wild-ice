// Public view of one lake's Ice Log: published comments and featured photos.
import { lakeComments } from "./comments.js";
import { HttpError, json } from "./http.js";

export async function getLake(env, request, lakeId) {
  if (!/^[wr]\d{1,12}$/.test(lakeId)) throw new HttpError(404, "Unknown lake");
  return json({ comments: await lakeComments(env, lakeId), photos: [] });
}
