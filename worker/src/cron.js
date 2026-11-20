// Daily: free photo space and, at most once a week, remind the owner of items that
// have waited more than a week. Nothing else ever notifies the owner from here.
import { pendingCounts } from "./review.js";

const DAY = 86400_000;
const KEEP_PENDING_DAYS = 21;
const REMIND_AFTER_DAYS = 7;

const ago = (days) => new Date(Date.now() - days * DAY).toISOString();
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

async function cleanPhotos(env) {
  const { results } = await env.DB.prepare(
    `SELECT id, public_id, status FROM photos
     WHERE (status = 'pending' AND created_at < ?) OR status = 'rejected'`,
  ).bind(ago(KEEP_PENDING_DAYS)).all();
  for (const p of results) {
    await env.PHOTOS.delete(`photo:${p.public_id}`);
    if (p.status === "pending") {
      await env.DB.prepare("UPDATE photos SET status = 'rejected', decided_at = ? WHERE id = ?")
        .bind(new Date().toISOString(), p.id).run();
    }
  }
}

async function remind(env) {
  if (!env.NTFY_TOPIC) return;
  const last = await env.PHOTOS.get("meta:last_reminder");
  if (last && last > ago(REMIND_AFTER_DAYS)) return;
  const old = await pendingCounts(env, ago(REMIND_AFTER_DAYS));
  if (old.comments + old.photos === 0) return;
  const parts = [];
  if (old.comments) parts.push(plural(old.comments, "comment"));
  if (old.photos) parts.push(plural(old.photos, "photo"));
  try {
    const r = await fetch(`https://ntfy.sh/${env.NTFY_TOPIC}`, {
      method: "POST",
      headers: { Title: "Wild Ice: items waiting" },
      body: `${parts.join(", ")} waiting over a week`,
    });
    if (!r.ok) {
      console.error("reminder failed: HTTP", r.status); // never log the topic
      return;
    }
  } catch (err) {
    console.error("reminder failed:", err && err.name);
    return;
  }
  await env.PHOTOS.put("meta:last_reminder", new Date().toISOString());
}

export async function scheduled(controller, env, ctx) {
  await cleanPhotos(env);
  await remind(env);
}
