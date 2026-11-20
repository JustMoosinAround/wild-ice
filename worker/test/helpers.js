import { SELF } from "cloudflare:test";

export const SITE = "https://justmoosinaround.github.io";

export function call(method, path, { body, token, headers = {} } = {}) {
  const h = { Origin: SITE, ...headers };
  if (body !== undefined) h["Content-Type"] = "application/json";
  if (token) h.Authorization = `Bearer ${token}`;
  return SELF.fetch(`https://worker.test${path}`, {
    method, headers: h, body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function codeOf(inviteUrl) {
  return inviteUrl.split("#invite=")[1];
}

// Bootstrap the owner and return their device key.
export async function owner() {
  const r = await call("POST", "/api/bootstrap", { body: { name: "Owner" }, token: "test-bootstrap" });
  const { invite_url } = await r.json();
  const d = await (await call("POST", "/api/invites/redeem", { body: { code: codeOf(invite_url) } })).json();
  return d.device_key;
}

// Owner invites a friend; return the friend's device key.
export async function friend(ownerKey, name = "Pat") {
  const inv = await (await call("POST", "/api/invites", { body: { name }, token: ownerKey })).json();
  const d = await (await call("POST", "/api/invites/redeem", { body: { code: codeOf(inv.invite_url), name } })).json();
  return d.device_key;
}
