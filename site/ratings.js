// Rating / pin / hide files saved to the repo through the GitHub contents API.
// ES module, no dependencies; usable from the page and from node tests.

export const QUEUE_KEY = "wildice.queue";
export const CREDS_KEY = "wildice.creds";
export const RATINGS = ["skated", "snow", "water", "rough"];
export const ACTIONS = ["pin", "unpin", "hide", "unhide"];

function localDay(now) {
  // Local date in America/Anchorage (en-CA formats as YYYY-MM-DD).
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Anchorage", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(now);
}

export function buildRatingFile(lakeId, rating, note, now) {
  if (!RATINGS.includes(rating)) throw new Error(`invalid rating: ${rating}`);
  const day = localDay(now);
  return {
    path: `ratings/${day}-${now.getTime()}-${lakeId}.json`,
    content: JSON.stringify({ lake_id: lakeId, day, rating, note: note || "" }),
  };
}

export function buildPrefFile(lakeId, action, now) {
  if (!ACTIONS.includes(action)) throw new Error(`invalid action: ${action}`);
  return {
    path: `prefs/${now.getTime()}-${lakeId}.json`,
    content: JSON.stringify({ lake_id: lakeId, action }),
  };
}

function toBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

export async function saveFile(file, { token, repo }, fetchFn = fetch) {
  const url = `https://api.github.com/repos/${repo}/contents/${file.path}`;
  const res = await fetchFn(url, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message: `wildice: ${file.path}`, content: toBase64(file.content) }),
  });
  if (!res.ok) throw new Error(`GitHub save failed (${res.status})`);
}

function readQueue(storage) {
  try { return JSON.parse(storage.getItem(QUEUE_KEY) || "[]"); } catch { return []; }
}

export function enqueue(storage, file) {
  const q = readQueue(storage);
  q.push(file);
  storage.setItem(QUEUE_KEY, JSON.stringify(q));
}

let flushing = false;

export async function flushQueue(storage, creds, fetchFn = fetch) {
  if (!creds || !creds.token || !creds.repo || flushing) return 0;
  flushing = true;
  try {
    const q = readQueue(storage);
    const failed = [];
    let saved = 0;
    for (const file of q) {
      try { await saveFile(file, creds, fetchFn); saved++; } catch { failed.push(file); }
    }
    // Keep anything enqueued while we were sending.
    const added = readQueue(storage).slice(q.length);
    storage.setItem(QUEUE_KEY, JSON.stringify(failed.concat(added)));
    return saved;
  } finally {
    flushing = false;
  }
}
