import { createExecutionContext, createScheduledController, env, waitOnExecutionContext } from "cloudflare:test";
import { afterEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index.js";

const DAY = 86400_000;
const ago = (days) => new Date(Date.now() - days * DAY).toISOString();
let pushes = [];

function stubNtfy() {
  pushes = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    pushes.push({ url: typeof input === "string" ? input : input.url, init });
    return new Response("ok");
  });
}

afterEach(() => vi.restoreAllMocks());

async function runCron() {
  const ctx = createExecutionContext();
  await worker.scheduled(createScheduledController({ scheduledTime: Date.now(), cron: "17 18 * * *" }), env, ctx);
  await waitOnExecutionContext(ctx);
}

async function pendingComment(days) {
  await env.DB.prepare(
    `INSERT INTO comments (id, lake_id, name, text, sender_hash, created_at, status)
     VALUES (?, 'w1', 'Sam', 'hi', 'x', ?, 'pending')`,
  ).bind(crypto.randomUUID(), ago(days)).run();
}

async function photo(status, days, publicId = crypto.randomUUID()) {
  await env.DB.prepare(
    `INSERT INTO photos (id, public_id, lake_id, friend_id, created_at, status)
     VALUES (?, ?, 'w1', 'f', ?, ?)`,
  ).bind(crypto.randomUUID(), publicId, ago(days), status).run();
  await env.PHOTOS.put(`photo:${publicId}`, "bytes");
  return publicId;
}

describe("daily cron", () => {
  it("reminder only when something waited > 7 days", async () => {
    stubNtfy();
    await pendingComment(6);
    await runCron();
    expect(pushes).toHaveLength(0);
    await pendingComment(8);
    await photo("pending", 9);
    await runCron();
    expect(pushes).toHaveLength(1);
    expect(pushes[0].url).toBe("https://ntfy.sh/test-topic");
    expect(pushes[0].init.headers.Title).toBe("Wild Ice: items waiting");
    expect(pushes[0].init.body).toBe("1 comment, 1 photo waiting over a week");
  });

  it("no second reminder within 7 days", async () => {
    stubNtfy();
    await pendingComment(10);
    await runCron();
    await runCron();
    expect(pushes).toHaveLength(1);
    await env.PHOTOS.put("meta:last_reminder", ago(8));
    await runCron();
    expect(pushes).toHaveLength(2);
  });

  it("stale pending photos cleaned after 21 days", async () => {
    stubNtfy();
    const old = await photo("pending", 22);
    const fresh = await photo("pending", 3);
    const featured = await photo("featured", 60);
    const rejected = await photo("rejected", 1);
    await runCron();
    expect(await env.PHOTOS.get(`photo:${old}`)).toBeNull();
    expect(await env.DB.prepare("SELECT status FROM photos WHERE public_id = ?").bind(old).first("status")).toBe("rejected");
    expect(await env.PHOTOS.get(`photo:${fresh}`)).toBe("bytes");
    expect(await env.PHOTOS.get(`photo:${featured}`)).toBe("bytes");
    // rejected rows had their bytes deleted when rejected; the cron leaves them alone
    expect(await env.PHOTOS.get(`photo:${rejected}`)).toBe("bytes");
  });
});
