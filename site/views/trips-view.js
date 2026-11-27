// Trip reports: what members skated, with their story, photo, track time and kudos.
import { shortDate } from "../explore.js";

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  n.append(...kids.filter(Boolean));
  return n;
}

const RATING = { skated: "Skated", rough: "Rough ice", snow: "Snow on ice", water: "Open water" };

// opts: {lakeName(id), openLake(id) | null, photoUrl(publicId), avatar(r) -> Node,
//        canKudos: bool, onKudos(r) -> Promise<{kudos, gave_kudos} | null>}
export function tripCard(r, opts) {
  const head = el("div", { class: "trip-head" }, opts.avatar(r),
    el("span", { class: "trip-who" }, el("b", { text: r.name }),
      el("span", { class: "meta" }, opts.openLake
        ? el("button", { type: "button", class: "linkish", text: opts.lakeName(r.lake_id), onclick: () => opts.openLake(r.lake_id) })
        : null, (opts.openLake ? " · " : "") + shortDate(r.day))));
  const facts = [RATING[r.rating] || r.rating, r.grade, r.track_minutes ? `${r.track_minutes} min on the ice` : null].filter(Boolean);
  const img = r.photo ? el("img", { class: "trip-photo", src: opts.photoUrl(r.photo), alt: "", loading: "lazy" }) : null;
  if (img) img.addEventListener("error", () => img.remove(), { once: true });
  const kudos = el("button", { type: "button", class: "kudos" + (r.gave_kudos ? " on" : ""), "aria-pressed": String(!!r.gave_kudos),
    title: opts.canKudos ? "Give kudos" : "Join to give kudos", text: `👏 ${r.kudos || 0}` });
  kudos.addEventListener("click", async () => {
    if (!opts.canKudos) { location.hash = "#join"; return; }
    const res = await opts.onKudos(r);
    if (!res) return;
    r.kudos = res.kudos; r.gave_kudos = res.gave_kudos;
    kudos.textContent = `👏 ${r.kudos}`;
    kudos.classList.toggle("on", r.gave_kudos);
    kudos.setAttribute("aria-pressed", String(r.gave_kudos));
  });
  return el("li", { class: "trip" }, head,
    el("p", { class: "trip-facts", text: facts.join(" · ") }),
    r.story ? el("p", { class: "trip-story", text: r.story }) : null, img, kudos);
}

// The Trip reports feed (Explore): newest first.
export async function renderTrips(mount, opts, limit = 0) {
  mount.replaceChildren(el("p", { class: "meta", text: "Loading trip reports…" }));
  const reports = await opts.load().catch(() => null);
  if (!reports) { mount.replaceChildren(el("p", { class: "meta", text: "Couldn't load. Try again later." })); return; }
  if (!reports.length) {
    mount.replaceChildren(el("p", { class: "meta", text: "No trip reports yet." }));
    return;
  }
  mount.replaceChildren(el("ol", { class: "trips" }, ...(limit ? reports.slice(0, limit) : reports).map((r) => tripCard(r, opts))));
}
