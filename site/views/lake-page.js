// Lake page hero: photo, name, label, badges, Save.
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

// opts: {d, photo, chip (element), badges: string[], saved: bool, onSave()}
export function heroSection(opts) {
  const { d } = opts;
  const img = opts.photo ? el("img", { class: "hero-photo", src: opts.photo, alt: d.name, loading: "lazy" }) : null;
  if (img) img.addEventListener("error", () => img.remove(), { once: true });
  // No onSave (the view-only embed): no Save button.
  const save = opts.onSave ? el("button", { type: "button", class: "save" + (opts.saved ? " on" : ""),
    "aria-pressed": String(!!opts.saved), text: opts.saved ? "♥ Saved" : "♡ Save", onclick: opts.onSave }) : null;
  return el("div", { class: "hero" }, img,
    el("div", { class: "hero-head" }, el("h2", { text: (d.pinned ? "★ " : "") + d.name }), save),
    el("div", { class: "hero-chips" }, opts.chip, ...opts.badges.map((b) => el("span", { class: "badge", text: b }))));
}
