// Explore tab: the feed of lakes that are in, with sort chips and a List/Map switch.
import { CHIPS, badges, evidenceLine, inLakes, sortLakes } from "../explore.js";

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

// opts: {status, props, ctx: {runDate, skated: Set|null}, chip, onChip(id), onMap(), openLake(id), photoUrl(d)}
export function renderExplore(mount, opts) {
  const { status, props, ctx } = opts;
  const chips = CHIPS.filter((c) => c.id !== "new_to_you" || ctx.skated);
  const chip = chips.some((c) => c.id === opts.chip) ? opts.chip : "just_in";
  const list = sortLakes(inLakes(status.lakes), chip, props, ctx);
  const bar = el("div", { class: "chips", role: "tablist", "aria-label": "Sort lakes" },
    ...chips.map((c) => el("button", { type: "button", class: "chip-btn" + (c.id === chip ? " on" : ""),
      role: "tab", "aria-selected": String(c.id === chip), text: c.label, onclick: () => opts.onChip(c.id) })));
  const head = el("div", { class: "feed-head" },
    el("h2", { text: list.length ? `In now (${list.length})` : "Nothing looks in today" }),
    el("button", { type: "button", class: "act small", text: "Map", onclick: opts.onMap }));
  const feed = el("ol", { class: "feed" });
  for (const d of list) {
    const ev = evidenceLine(d, ctx.runDate);
    const src = opts.photoUrl(d);
    const img = src ? el("img", { class: "card-photo", src, alt: d.name, loading: "lazy" }) : null;
    if (img) img.addEventListener("error", () => img.remove(), { once: true });
    feed.append(el("li", {}, el("button", { type: "button", class: "card", onclick: () => opts.openLake(d.id) },
      img,
      el("span", { class: "card-body" },
        el("b", { class: "card-name", text: d.name }),
        el("span", { class: "badges" }, ...badges(d, props, ctx).map((b) => el("span", { class: "badge", text: b }))),
        el("span", { class: "evidence" + (ev.old ? " old" : ""), text: ev.text })))));
  }
  const kids = [head];
  if (list.length) kids.push(bar, feed);
  else {
    const soon = Object.entries(status.lakes).filter(([, d]) => d.label === "freezing" && !d.hidden)
      .map(([id, d]) => ({ id, ...d })).sort((a, b) => (b.thickness_cm || 0) - (a.thickness_cm || 0)).slice(0, 5);
    if (soon.length) {
      kids.push(el("h3", { text: "Closest to coming in" }),
        el("ol", { class: "feed" }, ...soon.map((d) => el("li", {}, el("button", { type: "button", class: "card slim",
          onclick: () => opts.openLake(d.id) }, el("span", { class: "card-body" }, el("b", { class: "card-name", text: d.name }),
          el("span", { class: "evidence", text: "Freezing" })))))));
    }
  }
  mount.replaceChildren(...kids);
}
