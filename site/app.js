import {
  buildRatingFile, buildPrefFile, enqueue, flushQueue, CREDS_KEY, QUEUE_KEY, RATINGS,
} from "./ratings.js";
import { renderWeatherChart } from "./chart.js";

const STYLE = {
  open_water: { fill: "#3b82f6", line: "#1d4ed8", text: "Open water" },
  freezing: { fill: "#14b8a6", line: "#0f766e", text: "Freezing" },
  likely_black_ice: { fill: "#0f172a", line: "#facc15", text: "Likely black ice" },
  snow_covered: { fill: "#f8fafc", line: "#6b7280", text: "Snow covered" },
  unknown: { fill: "#9ca3af", line: "#6b7280", text: "Unknown" },
};
// Map key, best skating first.
const KEY = [
  ["likely_black_ice", "Thick enough to skate, little snow, and a satellite sees ice"],
  ["freezing", "Ice forming, still too thin to skate"],
  ["unknown", "Thick enough, but no clear satellite look yet"],
  ["snow_covered", "Snow on the ice"],
  ["open_water", "No ice yet"],
];
const SKATE_LABELS = new Set(["likely_black_ice", "freezing"]);
const RATING_TEXT = { skated: "Skated", snow: "Snow", water: "Water", rough: "Rough" };

const $ = (id) => document.getElementById(id);
const store = (() => { try { return window.localStorage; } catch { return null; } })()
  || { _m: {}, getItem(k) { return this._m[k] ?? null; }, setItem(k, v) { this._m[k] = String(v); }, removeItem(k) { delete this._m[k]; } };

let map;
let currentId = null;
let status = { lakes: {} };
let features = [];
const layers = new Map(); // id -> {group, feature}

function getCreds() {
  try { return JSON.parse(store.getItem(CREDS_KEY)); } catch { return null; }
}
function pending() {
  try { return JSON.parse(store.getItem(QUEUE_KEY) || "[]").length; } catch { return 0; }
}
function flush() {
  return flushQueue(store, getCreds(), (...a) => fetch(...a), { onAuthFailed }).catch(() => 0);
}

// Bad token/repo: forget the creds (queue stays) and ask again.
function onAuthFailed() {
  store.removeItem(CREDS_KEY);
  const panel = $("panel");
  if (panel.hidden) {
    showMsg("GitHub rejected the token or repo — re-enter it on your next rating.");
    return;
  }
  const id = currentId;
  if (id && info(id)) renderPanel(id, "GitHub rejected the token or repo — re-enter");
  credsForm(() => flush().then(() => setStatus(pending() ? pending() + " waiting to upload" : "Saved")));
}

function showMsg(text) {
  const m = $("msg");
  m.textContent = text;
  m.hidden = !text;
}

function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const k of kids) if (k) n.append(k);
  return n;
}

function info(id) { return status.lakes[id]; }

function lakeStyle(id) {
  const d = info(id);
  const s = STYLE[d ? d.label : "unknown"] || STYLE.unknown;
  const hidden = d && d.hidden;
  return {
    color: s.line, fillColor: s.fill, weight: d && d.label === "likely_black_ice" ? 3 : 1.5,
    fillOpacity: hidden ? 0.3 : 0.85, opacity: hidden ? 0.3 : 1,
  };
}

function visible(id) {
  if (!$("only-skate").checked) return true;
  const d = info(id);
  return !!d && SKATE_LABELS.has(d.label);
}

function build() {
  for (const { group } of layers.values()) group.remove();
  layers.clear();
  for (const f of features) {
    const id = f.properties.id;
    const group = L.layerGroup();
    const st = lakeStyle(id);
    if (f.geometry) {
      L.geoJSON(f, { style: () => st }).eachLayer((l) => group.addLayer(l));
    }
    const d = info(id);
    // A marker for every lake: polygons are invisible at region zoom, and
    // lakes without geometry are only reachable this way.
    if (d && d.pinned) {
      group.addLayer(L.marker([f.properties.lat, f.properties.lon], {
        icon: L.divIcon({ className: "", html: '<div class="star">★</div>', iconSize: [24, 24], iconAnchor: [12, 12] }),
        opacity: d.hidden ? 0.3 : 1, title: d.name,
      }));
    } else {
      group.addLayer(L.circleMarker([f.properties.lat, f.properties.lon], { ...st, radius: 7 }));
    }
    group.eachLayer((l) => l.on("click", () => openLake(id, false)));
    layers.set(id, { group, feature: f });
  }
  applyFilter();
}

function applyFilter() {
  for (const [id, { group }] of layers) {
    if (visible(id)) group.addTo(map); else group.remove();
  }
}

function zoomTo(id) {
  const rec = layers.get(id);
  if (!rec) return;
  const f = rec.feature;
  if (f.geometry) {
    map.fitBounds(L.geoJSON(f).getBounds(), { maxZoom: 16, padding: [40, 40] });
  } else {
    map.setView([f.properties.lat, f.properties.lon], 15);
  }
}

function closePanel() {
  $("panel").hidden = true;
  if (location.hash.startsWith("#lake=")) history.replaceState(null, "", location.pathname + location.search);
}

function openLake(id, zoom) {
  if (!info(id)) return;
  if (zoom) zoomTo(id);
  history.replaceState(null, "", "#lake=" + encodeURIComponent(id));
  renderPanel(id);
}

function renderPanel(id, statusText) {
  currentId = id;
  const d = info(id);
  const s = STYLE[d.label] || STYLE.unknown;
  const panel = $("panel");
  panel.replaceChildren();
  panel.append(el("button", { class: "close", "aria-label": "Close", text: "×", onclick: closePanel }));
  panel.append(el("h2", { text: (d.pinned ? "★ " : "") + d.name }));
  const chip = el("span", { class: "chip", text: s.text });
  chip.style.background = s.fill;
  chip.style.borderColor = s.line;
  chip.style.color = ["snow_covered", "unknown"].includes(d.label) ? "#0f172a" : "#fff";
  panel.append(el("div", {}, chip, el("span", { class: "meta", text: "  " + d.confidence + " confidence" })));
  panel.append(el("p", { class: "meta", text: d.reason }));
  if (d.warning) panel.append(el("p", { class: "warn", text: d.warning }));
  if (d.thickness_cm != null) {
    panel.append(el("p", { class: "est", text: "est. " + d.thickness_cm + " cm" }));
    panel.append(el("p", { class: "disc", text: status.disclaimer || "Rough estimate only — check ice yourself." }));
  }
  // Daily color history, oldest first. Published history stops at yesterday, so add today.
  const days = (d.history || []).filter((h) => h.day !== status.run_date);
  if (status.run_date) days.push({ day: status.run_date, label: d.label });
  if (days.length > 1) {
    const recent = days.slice(-14);
    panel.append(el("p", { class: "strip-head", text: "Color each day" }));
    const strip = el("div", { class: "strip", "aria-label": "Lake color each day, oldest first" });
    recent.forEach((h, i) => {
      const hs = STYLE[h.label] || STYLE.unknown;
      const c = el("span", { title: shortDay(h.day) + ": " + hs.text });
      c.style.background = hs.fill;
      c.style.borderColor = hs.line;
      if (i === recent.length - 1) c.className = "today";
      strip.append(c);
    });
    panel.append(strip);
    panel.append(el("div", { class: "strip-ends" },
      el("span", { text: shortDay(recent[0].day) }), el("span", { text: "Today" })));
  }
  const chart = el("div", { class: "wx-mount" });
  panel.append(chart);
  loadChart(id, chart);
  if (d.thumb) panel.append(el("img", { class: "thumb", src: "data/" + d.thumb, alt: d.name + " satellite thumbnail", loading: "lazy" }));
  if (typeof d.browser_url === "string" && d.browser_url.startsWith("https://")) {
    panel.append(el("a", { class: "cop", href: d.browser_url, target: "_blank", rel: "noopener", text: "Open in Copernicus Browser" }));
  }

  const note = el("input", { type: "text", placeholder: "Optional note", "aria-label": "Note", maxlength: "200" });
  const row = el("div", { class: "row" });
  for (const r of RATINGS) {
    row.append(el("button", {
      class: "act", text: RATING_TEXT[r],
      onclick: () => act(id, () => buildRatingFile(id, r, note.value.trim(), new Date()), "Rated: " + RATING_TEXT[r]),
    }));
  }
  panel.append(el("p", { class: "meta", text: "How was it?" }), row, note);

  const prow = el("div", { class: "row" });
  prow.append(el("button", {
    class: "act" + (d.pinned ? " on" : ""), text: d.pinned ? "★ Pinned" : "Pin",
    onclick: () => act(id, () => buildPrefFile(id, d.pinned ? "unpin" : "pin", new Date()),
      d.pinned ? "Unpinned" : "Pinned", (x) => { x.pinned = !x.pinned; }),
  }));
  prow.append(el("button", {
    class: "act" + (d.hidden ? " on" : ""), text: d.hidden ? "Hidden (tap to show)" : "Hide",
    onclick: () => act(id, () => buildPrefFile(id, d.hidden ? "unhide" : "hide", new Date()),
      d.hidden ? "Unhidden" : "Hidden", (x) => { x.hidden = !x.hidden; }),
  }));
  panel.append(prow);
  panel.append(el("a", { class: "cop", href: "#", text: "Reset GitHub token", onclick: (e) => {
    e.preventDefault();
    store.removeItem(CREDS_KEY);
    renderPanel(id, "Token cleared");
    credsForm(() => flush().then(() => setStatus(pending() ? pending() + " waiting to upload" : "Saved")));
  } }));
  panel.append(el("div", { class: "status", id: "status", text: statusText || (pending() ? pending() + " waiting to upload" : "") }));
  panel.hidden = false;
}

// Weather chart data is one small file per lake, fetched when its panel opens.
const seriesCache = new Map();
function loadChart(id, mount) {
  if (!seriesCache.has(id)) {
    seriesCache.set(id, fetch("data/series/" + encodeURIComponent(id) + ".json")
      .then((r) => (r.ok ? r.json() : null)).catch(() => null));
  }
  seriesCache.get(id).then((s) => {
    if (s && s.day && mount.isConnected) renderWeatherChart(s, mount);
  });
}

function setStatus(t) {
  const s = $("status");
  if (s) s.textContent = t;
}

function credsForm(onDone) {
  const form = el("form", {});
  const token = el("input", { type: "password", autocomplete: "off", "aria-label": "GitHub token", placeholder: "github_pat_...", required: "" });
  const repo = el("input", { type: "text", autocomplete: "off", "aria-label": "Repository", placeholder: "owner/repo", required: "", pattern: "[\\w.\\-]+/[\\w.\\-]+" });
  form.append(
    el("p", { class: "meta", text: "One-time setup: your fine-grained GitHub token (contents: write on this repo only). Stored only in this browser." }),
    el("label", { text: "Token" }), token, el("label", { text: "Repository" }), repo,
    el("button", { class: "act", type: "submit", text: "Save and continue", style: "width:100%;margin-top:8px" }),
  );
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    store.setItem(CREDS_KEY, JSON.stringify({ token: token.value.trim(), repo: repo.value.trim() }));
    form.remove();
    onDone();
  });
  $("panel").append(form);
  token.focus();
}

// Queue a file, apply an optimistic local change, then try to upload.
async function act(id, makeFile, doneText, mutate) {
  let file;
  try { file = makeFile(); } catch (e) { setStatus(e.message); return; }
  enqueue(store, file);
  if (mutate) { mutate(info(id)); build(); }
  const go = async () => {
    renderPanel(id, "Saving...");
    await flush();
    const left = pending();
    setStatus(left ? doneText + " - " + left + " waiting to upload (will retry)" : doneText + " - saved");
  };
  if (!getCreds()) {
    renderPanel(id, doneText + " - queued");
    credsForm(go);
  } else {
    await go();
  }
}

function showBanner() {
  const b = $("banner");
  if (status.stale_since) {
    b.textContent = "Data from " + status.stale_since + " — the daily job failed.";
    b.hidden = false;
  } else {
    b.hidden = true;
  }
}

function shortDay(iso) {
  const [y, m, dd] = iso.split("-").map(Number);
  return new Date(y, m - 1, dd).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function addKey() {
  const KEY_OPEN = "wildice.keyOpen";
  const ctl = L.control({ position: "bottomleft" });
  ctl.onAdd = () => {
    const box = el("details", { class: "key" });
    let open = null;
    try { open = store.getItem(KEY_OPEN); } catch { /* storage blocked */ }
    box.open = open === null ? window.innerWidth >= 700 : open === "1";
    box.addEventListener("toggle", () => {
      try { store.setItem(KEY_OPEN, box.open ? "1" : "0"); } catch { /* storage blocked */ }
    });
    box.append(el("summary", { text: "Key" }));
    for (const [label, desc] of KEY) {
      const s = STYLE[label];
      const sw = el("i", { class: "sw" });
      sw.style.background = s.fill;
      sw.style.borderColor = s.line;
      if (label === "likely_black_ice") sw.style.borderWidth = "3px";
      const row = el("div", { class: "key-row" });
      row.append(sw, el("span", {}, el("b", { text: s.text }), el("br"), desc));
      box.append(row);
    }
    const star = el("div", { class: "key-row" });
    star.append(el("i", { class: "star", text: "★" }), el("span", { text: "Pinned lake" }));
    const faded = el("div", { class: "key-row" });
    const fsw = el("i", { class: "sw" });
    fsw.style.cssText = "background:#3b82f6;border-color:#1d4ed8;opacity:.3";
    faded.append(fsw, el("span", { text: "Faded: hidden lake" }));
    box.append(star, faded);
    L.DomEvent.disableClickPropagation(box);
    L.DomEvent.disableScrollPropagation(box);
    return box;
  };
  ctl.addTo(map);
}

function routeHash() {
  const m = location.hash.match(/^#lake=(.+)$/);
  if (!m) return;
  const id = decodeURIComponent(m[1]);
  if (info(id)) openLake(id, true);
}

async function load() {
  const [g, s] = await Promise.all([
    fetch("data/lakes.geojson").then((r) => { if (!r.ok) throw new Error("lakes"); return r.json(); }),
    fetch("data/status.json").then((r) => { if (!r.ok) throw new Error("status"); return r.json(); }),
  ]);
  features = g.features;
  status = s;
}

async function main() {
  map = L.map("map").setView([61.2, -149.5], 8);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  addKey();
  $("only-skate").addEventListener("change", applyFilter);
  window.addEventListener("hashchange", routeHash);
  window.addEventListener("online", flush);
  flush();
  try {
    await load();
  } catch {
    showMsg("Could not load lake data.");
    return;
  }
  showBanner();
  build();
  routeHash();
}

main();
