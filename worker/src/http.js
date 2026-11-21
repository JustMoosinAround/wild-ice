// JSON responses, errors and CORS for the map's origin only.

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status, headers: { "Content-Type": "application/json", ...headers },
  });
}

export async function readJson(request) {
  try {
    const data = await request.json();
    if (data && typeof data === "object" && !Array.isArray(data)) return data;
  } catch { /* fall through */ }
  throw new HttpError(400, "Expected a JSON object");
}

export function withCors(response, request, env) {
  if (request.headers.get("Origin") !== env.SITE_ORIGIN) return response;
  const r = new Response(response.body, response);
  r.headers.set("Access-Control-Allow-Origin", env.SITE_ORIGIN);
  r.headers.set("Vary", "Origin");
  return r;
}

export function preflight(request, env) {
  const headers = { "Access-Control-Max-Age": "86400" };
  if (request.headers.get("Origin") === env.SITE_ORIGIN) {
    headers["Access-Control-Allow-Origin"] = env.SITE_ORIGIN;
    headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS";
    headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type";
    headers.Vary = "Origin";
  }
  return new Response(null, { status: 204, headers });
}

export const now = () => new Date().toISOString();
