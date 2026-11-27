// Explore (home): a season snapshot and rows of lakes worth a look, AllTrails-style.
import { SEASON_ORDER, badges, bigIce, comingIn, evidenceLine, inLakes, nearest, outlinePath, seasonCounts, sortLakes } from "../explore.js";

const SVG = "http://www.w3.org/2000/svg";

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

// No photo yet: the lake's own shape in its colour, on night ice.
function outlineArt(geometry, st) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 160 100");
  svg.setAttribute("class", "card-art");
  svg.setAttribute("aria-hidden", "true");
  const d = outlinePath(geometry, 160, 100, 14);
  const path = document.createElementNS(SVG, d ? "path" : "circle");
  if (d) path.setAttribute("d", d);
  else { path.setAttribute("cx", "80"); path.setAttribute("cy", "50"); path.setAttribute("r", "18"); } // no mapped outline
  path.setAttribute("fill", st.fill);
  path.setAttribute("fill-opacity", "0.85");
  path.setAttribute("stroke", st.line);
  path.setAttribute("stroke-width", "1.5");
  svg.append(path);
  return svg;
}

function lakeCard(d, opts, sub) {
  const st = opts.styleOf(d.label);
  const src = opts.photoUrl(d);
  const art = src ? el("img", { class: "card-photo", src, alt: "", loading: "lazy" }) : outlineArt(opts.geometry(d.id), st);
  if (src) art.addEventListener("error", () => art.replaceWith(outlineArt(opts.geometry(d.id), st)), { once: true });
  const chip = el("span", { class: "dot-chip" }, el("i", { style: `background:${st.fill};border-color:${st.line}` }), st.text);
  return el("li", {}, el("button", { type: "button", class: "card", onclick: () => opts.openLake(d.id) },
    art, el("span", { class: "card-body" }, el("b", { class: "card-name", text: d.name }), chip,
      sub ? el("span", { class: "card-sub", text: sub }) : null)));
}

function row(title, items, opts, subOf, more) {
  if (!items.length) return null;
  return el("section", { class: "home-row" },
    el("div", { class: "row-head" }, el("h2", { text: title }), more || null),
    el("ol", { class: "rail" }, ...items.map((d) => lakeCard(d, opts, subOf(d)))));
}

// opts: {status, props, ctx: {runDate, skated}, openLake(id), photoUrl(d), styleOf(label),
//        geometry(id), here(), locate(done), saved: string[], renderTrips(mount, limit), openTrips(),
//        onSeason(label), onMap()}
export function renderExplore(mount, opts) {
  const { status, props, ctx } = opts;
  const lakes = status.lakes;
  const counts = seasonCounts(lakes);
  const total = Object.values(counts).reduce((a, b) => a + b, 0) || 1;
  const ac = (d) => (props[d.id]?.area_acres ? Math.round(props[d.id].area_acres).toLocaleString("en-US") + " ac" : "");
  const kids = [];

  // Season snapshot: one bar, tap a colour for those lakes on the map.
  const inNow = counts.likely_black_ice + counts.rough_ice;
  kids.push(el("section", { class: "season" },
    el("div", { class: "season-big" }, el("b", { text: String(inNow) }), el("span", { text: inNow === 1 ? "lake in" : "lakes in" }),
      el("span", { class: "season-sub", text: `${counts.freezing} freezing · ${total.toLocaleString("en-US")} watched` })),
    el("div", { class: "season-bar", role: "group", "aria-label": "Lakes by condition" },
      ...SEASON_ORDER.filter((l) => counts[l]).map((l) => {
        const st = opts.styleOf(l);
        return el("button", { type: "button", class: "seg", title: `${counts[l]} ${st.text}`, "aria-label": `${counts[l]} ${st.text}: show on map`,
          style: `flex-grow:${Math.max(counts[l], total / 60)};background:${st.fill}`, onclick: () => opts.onSeason(l) });
      })),
    el("div", { class: "season-key" }, ...SEASON_ORDER.filter((l) => counts[l]).map((l) => {
      const st = opts.styleOf(l);
      return el("button", { type: "button", class: "key-item", onclick: () => opts.onSeason(l) },
        el("i", { style: `background:${st.fill};border-color:${st.line}` }), `${counts[l]} ${st.text}`);
    }))));

  const inList = sortLakes(inLakes(lakes), "just_in", props, ctx);
  kids.push(row("In now", inList, opts, (d) => [badges(d, props, ctx)[0], evidenceLine(d, ctx.runDate).text].filter(Boolean).join(" · "),
    el("button", { type: "button", class: "linkish", text: "Map", onclick: opts.onMap })));
  kids.push(row("Coming in", comingIn(lakes), opts, (d) => [ac(d), d.thickness_cm ? `~${Math.round(d.thickness_cm)} cm` : ""].filter(Boolean).join(" · ")));

  const trips = el("div", { class: "trips-box" });
  kids.push(el("section", { class: "home-row" }, el("div", { class: "row-head" }, el("h2", { text: "Trip reports" }),
    el("button", { type: "button", class: "linkish", text: "See all", onclick: opts.openTrips })), trips));
  opts.renderTrips(trips, 3);

  const here = opts.here();
  if (here) {
    kids.push(row("Near you", nearest(lakes, props, here), opts, (d) => `${d.mi < 10 ? d.mi.toFixed(1) : Math.round(d.mi)} mi`));
  } else {
    kids.push(el("section", { class: "home-row" }, el("div", { class: "row-head" }, el("h2", { text: "Near you" }),
      el("button", { type: "button", class: "linkish", text: "Use my location", onclick: () => opts.locate() }))));
  }
  const saved = (opts.saved || []).filter((id) => lakes[id]).map((id) => ({ id, ...lakes[id] }));
  kids.push(row("Your lakes", saved, opts, ac));
  kids.push(row("Big ice to watch", bigIce(lakes, props), opts, ac));
  mount.replaceChildren(...kids.filter(Boolean));
}
