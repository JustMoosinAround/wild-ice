// My lakes tab: saved lakes with today's status, and lakes this skater has skated.
import { evidenceLine, shortDate } from "../explore.js";

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

// opts: {status, saved: string[], skated: [{lake_id, day}] | null, labelText(label), openLake(id), joined: bool}
export function renderMine(mount, opts) {
  const { status } = opts;
  const row = (id, sub) => {
    const d = status.lakes[id];
    if (!d) return null;
    return el("li", {}, el("button", { type: "button", class: "skate-row", onclick: () => opts.openLake(id) },
      el("span", { class: "nm" }, el("b", { text: d.name }), el("span", { class: "meta", text: sub(d) }))));
  };
  const saved = opts.saved.map((id) => row(id, (d) => `${opts.labelText(d.label)} · ${evidenceLine(d, status.run_date).text}`)).filter(Boolean);
  const kids = [el("h2", { text: "My lakes" }), el("h3", { text: "Saved" })];
  kids.push(saved.length ? el("ol", { class: "skate-list" }, ...saved)
    : el("p", { class: "meta", text: "Tap ♡ Save on a lake to keep it here." }));
  kids.push(el("h3", { text: "Skated" }));
  if (!opts.joined) {
    kids.push(el("p", { class: "meta", text: "Join Wild Ice (free, just your name) to sync saved lakes across your phones and keep a list of lakes you've skated." }));
  } else {
    const sk = (opts.skated || []).map((s) => row(s.lake_id, () => `Last skated ${shortDate(s.day)}`)).filter(Boolean);
    kids.push(sk.length ? el("ol", { class: "skate-list" }, ...sk)
      : el("p", { class: "meta", text: "Lakes you report skating, or upload a track for, show here." }));
  }
  kids.push(el("p", { class: "meta foot" }, el("a", { href: opts.glossaryHref || "#glossary", text: "Glossary: what the colours, badges and warnings mean" })));
  mount.replaceChildren(...kids);
}
