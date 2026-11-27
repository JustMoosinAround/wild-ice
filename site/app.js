import { chartMarkers, renderWeatherChart } from "./chart.js";
import { searchLakes } from "./search.js";
import { renderExplore } from "./views/explore-view.js";
import { heroSection } from "./views/lake-page.js";
import { GLOSSARY } from "./glossary.js";
import { renderMine } from "./views/mine-view.js";
import { renderUpload } from "./views/upload-view.js";
import { avatarEl, avatarUrl, renderAccount } from "./views/account-view.js";
import { renderTrips, tripCard } from "./views/trips-view.js";
import { spotFeature } from "./track.js";
import { sharedText } from "./activitylink.js";
import { badges, shortDate } from "./explore.js";
import { ACCESS, DISTANCES, LABELS, SIZES, SKATE, activeCount, clean, defaults, passes } from "./mapfilter.js";

const SKATE_CM = 5; // config.yaml ice.skate_cm: past 2" the thickness doesn't matter
import {
  GRADES, flushReports, getDevice, inviteCodeFromHash, loadLake, ownerCall, postComment, prepPhoto,
  queueReport, queuedReports, redeemInvite, joinOpen, giveKudos, loadFeed, loadSpots, addSpot, strava, getSaved, setSaved, getSkated, account, inviteCodeFromText, makeReport, checkDevice, clearLegacy, inviteDecision,
} from "./icelog.js";
import { STRAVA_CLIENT_ID, TURNSTILE_SITEKEY, WORKER_URL } from "./config.js";

const STYLE = {
  open_water: { fill: "#3b82f6", line: "#1d4ed8", text: "Open water" },
  freezing: { fill: "#a78bfa", line: "#6d28d9", text: "Freezing" },  // violet: far from the ice-cyan of "Likely skateable"
  likely_black_ice: { fill: "#2fb3cf", line: "#facc15", text: "Likely skateable" },
  rough_ice: { fill: "#e07a3f", line: "#facc15", text: "Skateable, rough" },  // burnt orange: apart from Unknown grey
  snow_covered: { fill: "#f8fafc", line: "#6b7280", text: "Snow covered" },
  unknown: { fill: "#9ca3af", line: "#6b7280", text: "Unknown" },
};
// Map key, best skating first.
const KEY = [
  ["likely_black_ice", "Thick enough, little snow, and cracks, a cold satellite reading, radar or a skater confirm ice"],
  ["rough_ice", "Someone skated it but graded the ice D or worse"],
  ["freezing", "Ice forming, still too thin to skate"],
  ["unknown", "Thick enough, but nothing confirms it yet: a dark image alone could be open water"],
  ["snow_covered", "Snow on the ice"],
  ["open_water", "No ice yet"],
];
// "How was it?" choices: map color they set right away (rough keeps the current one).
const REPORT = {
  skated: { text: "Skateable", label: "likely_black_ice" },
  water: { text: "Open water", label: "open_water" },
  snow: { text: "Snow on ice", label: "snow_covered" },
  rough: { text: "Rough ice", label: null },
};
// ?embed: view-only map for other websites. No reports, pins or GitHub token.
const VIEW_ONLY = new URLSearchParams(location.search).has("embed");
const REPORTED_KEY = "wildice.reported"; // lake id -> {day, rating, note}, until the next daily run
const UNDO_MS = 5000;
let pendingReport = null; // {id, rating, note, timer, before}

const $ = (id) => document.getElementById(id);
const store = (() => { try { return window.localStorage; } catch { return null; } })()
  || { _m: {}, getItem(k) { return this._m[k] ?? null; }, setItem(k, v) { this._m[k] = String(v); }, removeItem(k) { delete this._m[k]; } };

let map;
let currentId = null;
let status = { lakes: {} };
let features = [];
const layers = new Map(); // id -> {group, feature}

function pending() { return queuedReports(store).length; }

// A short note above the tab bar that goes away by itself (or when tapped).
let msgTimer = null;
function showMsg(text) {
  const m = $("msg");
  m.textContent = text;
  m.hidden = !text;
  clearTimeout(msgTimer);
  if (text) msgTimer = setTimeout(() => { m.hidden = true; }, 6000);
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

// --- member-added spots: marshes, rivers, sloughs, ponds (reports only, no satellite) ---
const SPOT_KIND = { marsh: "Marsh", river: "River", slough: "Slough", pond: "Pond", other: "Spot" };
const SPOT_LABEL = { skated: "likely_black_ice", rough: "rough_ice", snow: "snow_covered", water: "open_water" };
let spotFeatures = []; // spot boxes as polygons, for matching uploaded tracks

function addSpots(list) {
  for (const sp of list) {
    if (status.lakes[sp.id]) continue;
    const r = sp.last_report;
    status.lakes[sp.id] = { name: sp.name, label: (r && SPOT_LABEL[r.rating]) || "unknown", spot: true, kind: sp.kind,
      added_by: sp.added_by, hidden: false, history: [], hazards: [],
      last_report: r ? { day: r.day, rating: r.rating, grade: r.grade } : null };
    features.push({ type: "Feature", properties: { id: sp.id, name: sp.name, lat: sp.lat, lon: sp.lon, spot: true, kind: sp.kind }, geometry: null });
    spotFeatures.push(spotFeature(sp));
  }
}

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
  const d = info(id);
  if (VIEW_ONLY && d && d.hidden) return false;
  const p = layers.get(id)?.feature.properties;
  return passes(mapFilter, p, d, { runDate: status.run_date, here });
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
    if (f.properties.spot) {
      // Member-added spots (no outline): a diamond, so they read apart from lakes.
      const icon = L.divIcon({ className: "spot-pin", iconSize: [18, 18],
        html: `<span style="background:${st.fillColor};border-color:${st.color}"></span>` });
      group.addLayer(L.marker([f.properties.lat, f.properties.lon], { icon, title: f.properties.name }));
    } else {
      group.addLayer(L.circleMarker([f.properties.lat, f.properties.lon], { ...st, radius: 7 }));
    }
    group.eachLayer((l) => l.on("click", () => openLake(id, false)));
    layers.set(id, { group, feature: f });
  }
  applyFilter();
}

// --- map tools: search (embedded map) and filter buttons under the zoom ---
const FILTER_KEY = "wildice.mapFilter";
let mapFilter = (() => { try { return clean(JSON.parse(localStorage.getItem(FILTER_KEY))); } catch { return defaults(); } })();
let here = null; // {lat, lon} once the viewer shares their location for "distance from me"
let hereNote = "";

function setFilter(f) {
  mapFilter = clean(f);
  try { localStorage.setItem(FILTER_KEY, JSON.stringify(mapFilter)); } catch { /* storage blocked */ }
  if (mapFilter.maxMiles && !here) locate();
  applyFilter();
  paintFilterButton();
  if (!$("filter-sheet").hidden) drawFilterSheet();
}

function locate() {
  if (!navigator.geolocation) { hereNote = "This browser can't share a location, so distance isn't applied."; return; }
  hereNote = "Finding you…";
  navigator.geolocation.getCurrentPosition(
    (pos) => { here = { lat: pos.coords.latitude, lon: pos.coords.longitude }; hereNote = ""; setFilter(mapFilter); },
    () => { hereNote = "Location is off, so distance isn't applied."; if (!$("filter-sheet").hidden) drawFilterSheet(); },
    { maximumAge: 600000, timeout: 15000 });
}

const ICON = {
  search: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5 21 21"/></svg>',
  filter: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"><path d="M3 5h18l-7 8.5V20l-4-2v-4.5z"/></svg>',
};

function closeTool() {
  for (const id of ["filter-sheet", "search-sheet"]) { const n = $(id); if (n) n.hidden = true; }
  for (const b of document.querySelectorAll(".map-tools button")) b.setAttribute("aria-expanded", "false");
}

function toggleTool(id, btn) {
  const open = $(id).hidden;
  closeTool();
  if (!open) return;
  $(id).hidden = false;
  btn.setAttribute("aria-expanded", "true");
  if (id === "filter-sheet") drawFilterSheet(); else $("q").focus();
}

function paintFilterButton() {
  const n = activeCount(mapFilter);
  const b = $("filter-btn");
  if (!b) return;
  b.classList.toggle("on", n > 0);
  b.querySelector(".badge-n")?.remove();
  if (n) b.append(el("span", { class: "badge-n", text: String(n) }));
}

function drawFilterSheet() {
  const f = mapFilter;
  const sheet = $("filter-sheet");
  const choice = (name, opts, value, set) => el("div", { class: "fchips", role: "radiogroup", "aria-label": name },
    ...opts.map(([v, t]) => el("button", { type: "button", class: "fchip" + (v === value ? " on" : ""), role: "radio",
      "aria-checked": String(v === value), text: t, onclick: () => setFilter(set(v)) })));
  const shown = mapFilter.labels;
  const conds = el("div", { class: "fchips" }, ...LABELS.map((l) => {
    const st = STYLE[l];
    const sw = el("i", { class: "sw" }); sw.style.background = st.fill; sw.style.borderColor = st.line;
    return el("button", { type: "button", class: "fchip" + (shown.includes(l) ? " on" : ""), "aria-pressed": String(shown.includes(l)),
      onclick: () => setFilter({ ...f, labels: shown.includes(l) ? shown.filter((x) => x !== l) : [...shown, l] }) }, sw, st.text);
  }));
  const count = [...layers.keys()].filter(visible).length;
  const justIn = el("input", { type: "checkbox", onchange: (e) => setFilter({ ...f, justIn: e.target.checked }) });
  justIn.checked = f.justIn;
  sheet.replaceChildren(...[
    el("div", { class: "fhead" }, el("b", { text: `Filter · ${count} lakes` }),
      el("button", { type: "button", class: "fclose", "aria-label": "Close", text: "✕", onclick: closeTool })),
    el("h4", { text: "Conditions" }),
    el("div", { class: "fquick" },
      el("button", { type: "button", class: "linkish", text: "Skateable or freezing", onclick: () => setFilter({ ...f, labels: [...SKATE] }) }),
      el("button", { type: "button", class: "linkish", text: "All", onclick: () => setFilter({ ...f, labels: [...LABELS] }) })),
    conds,
    el("h4", { text: "Lake size" }), choice("Lake size", SIZES, f.minAcres, (v) => ({ ...f, minAcres: v })),
    el("h4", { text: "Access" }), choice("Access", ACCESS, f.access, (v) => ({ ...f, access: v })),
    el("h4", { text: "Distance" }), choice("Distance from me", DISTANCES, f.maxMiles, (v) => ({ ...f, maxMiles: v })),
    hereNote ? el("p", { class: "meta", text: hereNote }) : null,
    el("label", { class: "fcheck" }, justIn, " Just in (came in the last 3 days)"),
    activeCount(f) ? el("button", { type: "button", class: "act small", text: "Clear filters", onclick: () => setFilter(defaults()) }) : null,
  ].filter(Boolean));
}

function addMapTools() {
  const ctl = L.control({ position: "topleft" });
  ctl.onAdd = () => {
    const box = el("div", { class: "leaflet-bar map-tools" });
    if (VIEW_ONLY) {
      const sb = el("button", { type: "button", title: "Find a lake", "aria-label": "Find a lake", "aria-expanded": "false" });
      sb.innerHTML = ICON.search;
      sb.addEventListener("click", () => toggleTool("search-sheet", sb));
      box.append(sb);
    }
    const fb = el("button", { type: "button", id: "filter-btn", title: "Filter lakes", "aria-label": "Filter lakes", "aria-expanded": "false" });
    fb.innerHTML = ICON.filter;
    fb.addEventListener("click", () => toggleTool("filter-sheet", fb));
    box.append(fb);
    L.DomEvent.disableClickPropagation(box);
    return box;
  };
  ctl.addTo(map);
  const holder = map.getContainer();
  const sheet = el("div", { id: "filter-sheet", class: "map-sheet", hidden: true });
  holder.append(sheet);
  if (VIEW_ONLY) {
    const ss = el("div", { id: "search-sheet", class: "map-sheet search-sheet", hidden: true });
    ss.append(document.querySelector(".search")); // the embedded map's search lives under the button
    holder.append(ss);
  }
  for (const n of holder.querySelectorAll(".map-sheet")) {
    L.DomEvent.disableClickPropagation(n);
    L.DomEvent.disableScrollPropagation(n);
  }
  // A tap on a chip redraws the sheet, detaching the chip; Leaflet then sees a map click. Ignore those.
  map.on("click", (e) => { if (e.originalEvent?.target?.isConnected !== false) closeTool(); });
  paintFilterButton();
  if (mapFilter.maxMiles) locate();
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
  commitReport();
  $("panel").hidden = true;
  if (location.hash.startsWith("#lake=")) history.replaceState(null, "", location.pathname + location.search);
}

function openLake(id, zoom) {
  if (!info(id)) return;
  if (pendingReport && pendingReport.id !== id) commitReport();
  if (zoom) zoomTo(id);
  history.replaceState(null, "", "#lake=" + encodeURIComponent(id));
  renderPanel(id);
}

function todayLocal() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Anchorage", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

function readReported() {
  try { return JSON.parse(store.getItem(REPORTED_KEY) || "{}") || {}; } catch { return {}; }
}

// Show my own reports until a daily run newer than the report has picked them up.
function applyReported(id, rep) {
  const d = info(id);
  if (!d || !rep) return;
  const r = REPORT[rep.rating];
  if (r && r.label) d.label = r.label;
  if (rep.rating === "water") d.thickness_cm = 0;
  d.reported = rep;
}

function overlayReported() {
  const all = readReported();
  for (const [id, rep] of Object.entries(all)) {
    if (status.run_date && rep.day < status.run_date) { delete all[id]; continue; }
    applyReported(id, rep);
  }
  try { store.setItem(REPORTED_KEY, JSON.stringify(all)); } catch { /* storage blocked */ }
}

const ICELOG = { fetch: (...a) => fetch(...a), storage: store, base: WORKER_URL };
const GRADED = new Set(["skated", "rough"]);

function canLog() { return !VIEW_ONLY && WORKER_URL && getDevice(store); }

function reportSection(id) {
  const d = info(id);
  const box = el("div", { class: "report" });
  const p = pendingReport && pendingReport.id === id ? pendingReport : null;
  if (p) {
    const what = REPORT[p.rating].text;
    if (p.timer) {
      box.append(el("p", { class: "report-msg", text: "Logging " + what + " for today" }),
        el("div", { class: "row" },
          el("button", { class: "act", text: "Undo", onclick: undoReport }),
          el("button", { class: "act", text: "Add details", onclick: () => {
            clearTimeout(p.timer); p.timer = null; p.noting = true; renderPanel(id);
          } })));
    } else if (p.noting) {
      box.append(el("p", { class: "report-msg", text: what }), detailsForm(id, p));
    }
    return box;
  }
  const mine = d.reported && d.reported.day === todayLocal() ? d.reported : null;
  box.append(el("p", { class: "report-head", text: mine
    ? "You logged " + REPORT[mine.rating].text.toLowerCase() + " today. Changed?"
    : "How's the ice?" }));
  const grid = el("div", { class: "report-grid" });
  for (const [r, c] of Object.entries(REPORT)) {
    const sw = el("i", { class: "sw" });
    const st = STYLE[c.label || "unknown"];
    sw.style.background = st.fill;
    sw.style.borderColor = st.line;
    grid.append(el("button", {
      class: "act rep" + (mine && mine.rating === r ? " sel" : ""), type: "button",
      onclick: () => startReport(id, r),
    }, sw, c.text));
  }
  box.append(grid,
        el("button", { type: "button", class: "act small", text: "⇪ Upload a track", onclick: () => { closePanel(); showTab("upload"); } }));
  return box;
}

// Grade (for Skateable / Rough), note, photo and location for the pending report.
function detailsForm(id, p) {
  const form = el("form", { class: "details" });
  if (GRADED.has(p.rating)) {
    const chips = el("div", { class: "grades", role: "radiogroup", "aria-label": "Ice quality grade" });
    for (const g of GRADES) {
      chips.append(el("button", {
        type: "button", class: "grade" + (p.grade === g ? " sel" : ""), role: "radio",
        "aria-checked": String(p.grade === g), text: g,
        onclick: () => { p.grade = p.grade === g ? null : g; renderPanel(id); },
      }));
    }
    form.append(el("p", { class: "meta", text: "Grade (optional)" }), chips);
  }
  const note = el("textarea", { placeholder: "How was it?",
    "aria-label": "Trip report", maxlength: "1000", rows: "4" });
  note.value = p.story || "";
  note.addEventListener("input", () => { p.story = note.value; });
  const photo = el("input", { type: "file", accept: "image/jpeg,image/*", "aria-label": "Photo", class: "file-in", id: "rep-photo" });
  const photoMsg = el("p", { class: "meta", text: p.photo ? "Photo ready" + (p.photo.gps ? " (with its location)" : "") : "" });
  photo.addEventListener("change", async () => {
    const file = photo.files && photo.files[0];
    if (!file) return;
    photoMsg.textContent = "Preparing photo…";
    try {
      await loadScript("https://cdn.jsdelivr.net/npm/exifr@7.1.3/dist/lite.umd.js");
      p.photo = await prepPhoto(file);
      renderPanel(id);
    } catch {
      photoMsg.textContent = "Couldn't read that photo";
    }
  });
  form.append(note,
    el("label", { class: "act file-label", for: "rep-photo", text: p.photo ? "📷 Change photo" : "📷 Add photo" }), photo, photoMsg);
  if (!(p.photo && p.photo.gps)) {
    const where = el("button", { type: "button", class: "act", text: p.gps ? "Location added ✓" : "Use my location" });
    where.addEventListener("click", () => {
      if (!navigator.geolocation) return;
      where.textContent = "Finding you…";
      navigator.geolocation.getCurrentPosition(
        (pos) => { p.gps = { lat: pos.coords.latitude, lon: pos.coords.longitude, source: "device" }; renderPanel(id); },
        () => { where.textContent = "Location not available"; },
        { enableHighAccuracy: true, timeout: 15000 });
    });
    form.append(where);
  }
  form.append(el("button", { class: "act", type: "submit", text: "Post trip report" }));
  form.addEventListener("submit", (e) => { e.preventDefault(); p.story = note.value.trim(); commitReport(); });
  return form;
}

const scripts = new Map();
function loadScript(src) {
  if (!scripts.has(src)) {
    scripts.set(src, new Promise((resolve, reject) => {
      const tag = el("script", { src, async: "" });
      tag.onload = resolve;
      tag.onerror = () => { scripts.delete(src); reject(new Error("load failed")); };
      document.head.append(tag);
    }));
  }
  return scripts.get(src);
}

function startReport(id, rating) {
  if (pendingReport) commitReport();
  const d = info(id);
  pendingReport = { id, rating, note: "", grade: null, photo: null, gps: null,
    before: { label: d.label, reported: d.reported, thickness_cm: d.thickness_cm } };
  applyReported(id, { day: todayLocal(), rating, note: "" });
  build();
  pendingReport.timer = setTimeout(commitReport, UNDO_MS);
  renderPanel(id);
}

function undoReport() {
  const p = pendingReport;
  if (!p) return;
  clearTimeout(p.timer);
  pendingReport = null;
  const d = info(p.id);
  d.label = p.before.label;
  d.reported = p.before.reported;
  d.thickness_cm = p.before.thickness_cm;
  build();
  renderPanel(p.id, "Undone");
}

// Queue the pending report and try to send it (also called when the panel closes,
// another lake opens or the page is left during the undo window).
function commitReport() {
  const p = pendingReport;
  if (!p) return;
  clearTimeout(p.timer);
  pendingReport = null;
  const rep = { day: todayLocal(), rating: p.rating, note: p.note };
  const all = readReported();
  all[p.id] = rep;
  try { store.setItem(REPORTED_KEY, JSON.stringify(all)); } catch { /* storage blocked */ }
  applyReported(p.id, rep);
  queueReport(store, makeReport({ lakeId: p.id, rating: p.rating, grade: p.grade, note: p.note, story: p.story,
    photo: p.photo, gps: p.gps, day: rep.day }));
  if (currentId === p.id && !$("panel").hidden) renderPanel(p.id, "Logging…");
  sendQueue();
}

async function sendQueue() {
  if (!WORKER_URL) return;
  const r = await flushReports(ICELOG).catch(() => null);
  if (!r) return;
  if (r.revoked) {
    showMsg("This invite was switched off.");
    if (currentId && !$("panel").hidden) renderPanel(currentId);
    return;
  }
  let msg = r.sent ? "Logged" + (r.left ? ", " + r.left + " waiting to send" : "") : r.left ? r.left + " waiting to send (will retry)" : "";
  if (r.rejected) msg = "Not saved: " + r.rejected.join("; ");
  setStatus(msg);
}

// Field Notes (public part): featured photos and comments, for everyone.
function iceLogSection(id) {
  const box = el("section", { class: "icelog", "aria-label": "Field Notes" });
  const photos = el("div", { class: "featured" });
  const trips = el("ol", { class: "trips" });
  const list = el("ol", { class: "comments" });
  box.append(photos, el("h4", { text: "Trip reports" }), trips, el("h4", { text: "Comments" }), list, commentForm(id, list));
  if (!VIEW_ONLY && WORKER_URL && !getDevice(store)) box.append(joinPrompt("Join Wild Ice to post ice reports and photos"));
  loadLake(id, ICELOG).then(({ comments, photos: ph, reports = [] }) => {
    if (!box.isConnected) return;
    if (!reports.length) trips.append(el("li", { class: "meta", text: "None yet." }));
    for (const r of reports) trips.append(tripCard(r, tripOpts(false)));
    for (const p of ph || []) {
      photos.append(el("figure", {},
        el("img", { src: `${WORKER_URL}/api/photos/${encodeURIComponent(p.public_id)}`, alt: "Photo of the lake", loading: "lazy" }),
        el("figcaption", {}, avatarEl(avatarUrl(WORKER_URL, p.avatar), p.credit || "A skater", 20),
          document.createTextNode(" " + (p.credit || "A skater") + ", " + shortDay(p.created_at.slice(0, 10))))));
    }
    if (!comments.length) list.append(el("li", { class: "meta", text: "None yet." }));
    for (const c of comments) {
      list.append(el("li", { class: "comment" }, avatarEl(avatarUrl(WORKER_URL, c.avatar), c.name, 32),
        el("div", {}, el("b", { text: c.name }), el("span", { class: "meta", text: " · " + shortDay(c.created_at.slice(0, 10)) }), el("p", { text: c.text }))));
    }
  });
  return box;
}

// A member-added spot: no satellite or model, just what members report.
function renderSpot(id, d) {
  const panel = $("panel");
  const s = d.last_report ? (STYLE[d.label] || STYLE.unknown) : { ...STYLE.unknown, text: "No recent reports" };
  const chip = el("span", { class: "chip", text: s.text });
  chip.style.background = s.fill;
  chip.style.borderColor = s.line;
  chip.style.color = ["snow_covered", "unknown", "likely_black_ice"].includes(d.label) ? "#04090c" : "#fff";
  const last = d.last_report ? `Last report ${shortDay(d.last_report.day)}: ${REPORT[d.last_report.rating]?.text || d.last_report.rating}${d.last_report.grade ? " " + d.last_report.grade : ""}.` : "No reports in the last 2 weeks.";
  panel.replaceChildren(
    el("button", { class: "close", "aria-label": "Close", text: "×", onclick: closePanel }),
    heroSection({ d, photo: null, chip, badges: [SPOT_KIND[d.kind] || "Spot"], saved: savedIds.has(id),
      onSave: VIEW_ONLY ? null : () => toggleSave(id) }),
    el("p", { class: "meta", text: `${last} Added by ${d.added_by || "a skater"}. No satellite or ice model here: marshes, rivers and sloughs freeze their own way, so this spot's colour comes only from skaters' reports. Check the ice yourself.` }));
  panel.classList.add("page");
  if (canLog()) panel.append(reportSection(id));
  if (WORKER_URL) panel.append(iceLogSection(id));
  panel.hidden = false;
}

// --- install as an app: one button where the browser allows it (Android, desktop
// Chrome/Edge), a short how-to on iPhone (Safari has no install button for sites) ---
let installPrompt = null;
const installed = () => window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);

window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; paintInstall(); });
window.addEventListener("appinstalled", () => { installPrompt = null; paintInstall(); showMsg("Wild Ice is on your home screen"); });

function canOfferInstall() { return !VIEW_ONLY && !installed() && (installPrompt || isIOS()); }

async function doInstall() {
  if (installPrompt) {
    installPrompt.prompt();
    await installPrompt.userChoice.catch(() => null);
    installPrompt = null;
    paintInstall();
    return;
  }
  openPage("Install Wild Ice",
    el("ol", { class: "how" },
      el("li", { text: "Tap Share in Safari." }),
      el("li", { text: "Tap Add to Home Screen." }),
      el("li", { text: "Tap Add." })),
    );
}

function paintInstall() {
  const old = $("install-btn");
  if (!canOfferInstall()) { old?.remove(); return; }
  if (old) return;
  $("bar").append(el("button", { type: "button", id: "install-btn", class: "install-btn", text: "⤓ Install app", onclick: doInstall }));
}

// Connect Strava: off to Strava's consent page (its app on phones), back here with ?code.
function stravaAuthorize() {
  const state = crypto.randomUUID();
  try { sessionStorage.setItem("wildice.stravaState", state); } catch { /* fine */ }
  const back = location.origin + location.pathname;
  const mobile = /Android|iPhone|iPad/.test(navigator.userAgent);
  location.href = `https://www.strava.com/oauth/${mobile ? "mobile/" : ""}authorize?client_id=${encodeURIComponent(STRAVA_CLIENT_ID)}`
    + `&redirect_uri=${encodeURIComponent(back)}&response_type=code&approval_prompt=auto&scope=activity:read_all&state=${state}`;
}

// Back from Strava: finish connecting, then show the Upload tab.
async function stravaReturn() {
  const q = new URLSearchParams(location.search);
  if (!q.has("code") || !q.has("scope") || !STRAVA_CLIENT_ID) return false;
  history.replaceState(null, "", location.pathname + "#tab=upload");
  let want = null;
  try { want = sessionStorage.getItem("wildice.stravaState"); } catch { /* fine */ }
  if (want && q.get("state") !== want) { showMsg("Strava sign-in didn't match, try Connect again."); return true; }
  if (!getDevice(store)) { showMsg("Join Wild Ice first, then connect Strava."); return true; }
  const r = await strava.connect(q.get("code"), q.get("scope"), ICELOG).catch(() => null);
  showMsg(r && r.status === 200 ? "Strava connected" : (r && r.data.error) || "Couldn't connect Strava, try again");
  return true;
}

// "Share -> Wild Ice" on Android (manifest share_target) opens the app with the link in
// the address: hand it to the Upload tab once, then tidy the address.
let sharedLink = sharedText(location.search) || null;
function takeShared() { return sharedLink; } // kept across redraws until the tab changes

// Shared options for trip report cards (feed and lake pages).
function tripOpts(withLake) {
  return {
    lakeName: (id) => info(id)?.name || "A lake",
    openLake: withLake ? (id) => openLake(id, true) : null,
    photoUrl: (pid) => `${WORKER_URL}/api/photos/${encodeURIComponent(pid)}`,
    avatar: (r) => avatarEl(avatarUrl(WORKER_URL, r.avatar), r.name, 36),
    canKudos: !!getDevice(store),
    onKudos: (r) => giveKudos(r.id, ICELOG),
  };
}

// Embedded on a phone: one finger scrolls the host page, two fingers move and zoom the map.
function twoFingerMap() {
  if (!window.matchMedia?.("(pointer: coarse)").matches) return;
  map.dragging.disable();
  const hint = el("div", { class: "map-hint", text: "Two fingers to move the map" });
  hint.hidden = true;
  map.getContainer().append(hint);
  let timer = null;
  const box = map.getContainer();
  box.addEventListener("touchmove", (e) => {
    if (e.touches.length !== 1) { hint.hidden = true; return; }
    hint.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(() => { hint.hidden = true; }, 1800);
  }, { passive: true });
}

// --- anonymous usage counts (owner sees them on Review) ---
function platformName() {
  const ua = navigator.userAgent;
  if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "ios";
  if (/Android/.test(ua)) return "android";
  if (/Windows|Macintosh|Linux|CrOS/.test(ua)) return "desktop";
  return "other";
}

function countUse(path, body) {
  if (!WORKER_URL) return;
  fetch(WORKER_URL + path, { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) }).catch(() => { /* counts are best-effort */ });
}

// An installed copy (opened from the home screen) says hello once a day with a random id.
function pingInstall() {
  const installed = window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true;
  if (!installed) return;
  try {
    let id = store.getItem("wildice.installId");
    if (!id) { id = crypto.randomUUID(); store.setItem("wildice.installId", id); }
    const today = new Date().toISOString().slice(0, 10);
    if (store.getItem("wildice.pingDay") === today) return;
    store.setItem("wildice.pingDay", today);
    countUse("/api/ping", { id, platform: platformName() });
  } catch { /* storage blocked: don't count */ }
}

// A button that opens the sign-up page.
function joinPrompt(text) {
  return el("div", { class: "join-prompt" }, el("p", { class: "meta", text }),
    el("a", { class: "act join-btn", href: "#join", text: "Join Wild Ice" }));
}

// Sign-up: just a name and a quick bot check.
function showJoin() {
  if (!WORKER_URL) { showMsg("Sign-up isn't set up yet."); return; }
  if (getDevice(store)) { location.hash = "#account"; return; }
  const name = el("input", { type: "text", maxlength: "40", placeholder: "Your name", "aria-label": "Your name", autocomplete: "name" });
  const human = el("div", { class: "turnstile" });
  const msg = el("p", { class: "status" });
  let token = null;
  const form = el("form", { class: "comment-form" },
    el("p", { text: "Free. Just your name." }),
    name, human,
    el("p", { class: "disc", text: "Conditions are estimates. Check the ice yourself." }),
    el("button", { class: "act", type: "submit", text: "Join" }), msg);
  if (TURNSTILE_SITEKEY) {
    loadScript("https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit").then(() => {
      if (window.turnstile && human.isConnected) {
        window.turnstile.render(human, { sitekey: TURNSTILE_SITEKEY, callback: (t) => { token = t; } });
      }
    }).catch(() => { msg.textContent = "Couldn't load the check; try again later."; });
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!name.value.trim()) { msg.textContent = "Add your name"; name.focus(); return; }
    msg.textContent = "Joining…";
    const r = await joinOpen(name.value.trim(), token, ICELOG);
    if (!r.ok) {
      msg.textContent = r.error;
      if (window.turnstile) { window.turnstile.reset(human); token = null; }
      return;
    }
    savedIds = new Set(); markSaved(); loadMine(); paintMe();
    if (canOfferInstall()) {
      openPage(`Welcome, ${r.name}`, el("button", { type: "button", class: "act on", text: "⤓ Install app", onclick: doInstall }));
    } else {
      closePanel();
      showMsg(`Welcome, ${r.name}`);
    }
  });
  openPage("Join Wild Ice", form, pasteInvite());
  name.focus();
}

// "Have an invite?": paste the link here when the app can't open it (home-screen app).
function pasteInvite() {
  const input = el("input", { type: "text", placeholder: "Paste your invite link", "aria-label": "Invite link", autocomplete: "off" });
  const msg = el("p", { class: "status" });
  const form = el("form", { class: "comment-form" }, input, el("button", { class: "act", type: "submit", text: "Join" }), msg);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const code = inviteCodeFromText(input.value);
    if (!code) { msg.textContent = "That doesn't look like an invite link."; return; }
    input.value = "";
    showInvite(code);
  });
  return el("details", { class: "invite-paste" }, el("summary", { text: "Have a link from your other phone?" }), form);
}

function commentForm(id, list) {
  const device = getDevice(store);
  const form = el("form", { class: "comment-form" });
  const name = el("input", { type: "text", placeholder: "Your name", "aria-label": "Your name", maxlength: "40", required: "" });
  if (device) { name.value = device.name; name.hidden = true; } // members post under their name
  const text = el("textarea", { placeholder: "Add a comment", "aria-label": "Comment", maxlength: "500", rows: "3", required: "" });
  const msg = el("p", { class: "status" });
  const human = el("div", { class: "turnstile" });
  let token = null;
  form.append(name, text);
  if (!device) {
    form.append(human, el("p", { class: "meta", text: "Checked before posting." }));
    if (TURNSTILE_SITEKEY) {
      loadScript("https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit").then(() => {
        if (window.turnstile && human.isConnected) {
          window.turnstile.render(human, { sitekey: TURNSTILE_SITEKEY, callback: (t) => { token = t; } });
        }
      }).catch(() => { msg.textContent = "Couldn't load the check; try again later."; });
    }
  }
  form.append(el("button", { class: "act", type: "submit", text: "Post comment" }), msg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "Posting…";
    const r = await postComment({ lake_id: id, name: name.value.trim(), text: text.value.trim(), turnstile_token: token }, ICELOG);
    if (!r.ok) { msg.textContent = r.error; return; }
    text.value = "";
    if (r.status === "published") {
      renderPanel(id, "Comment posted"); // reloads the list from the worker
    } else {
      msg.textContent = "Thanks! It will appear once it's checked.";
    }
    if (!device && window.turnstile) { window.turnstile.reset(human); token = null; }
  });
  return form;
}

function renderPanel(id, statusText) {
  currentId = id;
  const d = info(id);
  if (d.spot) { renderSpot(id, d); return; }
  const s = STYLE[d.label] || STYLE.unknown;
  const panel = $("panel");
  panel.replaceChildren();
  const props = (layers.get(id) || {}).feature?.properties || {};
  if (props.area_acres) {
    let size = Math.round(props.area_acres).toLocaleString() + " ac";
    if (props.depth_m) size += " · " + Math.round(props.depth_m) + " m deep";
    panel.append(el("p", { class: "meta", text: size }));
  }
  const chip = el("span", { class: "chip", text: s.text });
  chip.style.background = s.fill;
  chip.style.borderColor = s.line;
  chip.style.color = ["snow_covered", "unknown", "likely_black_ice"].includes(d.label) ? "#04090c" : "#fff";
  panel.prepend(heroSection({ d, photo: photoUrl(d), chip,
    badges: badges({ id, ...d }, { [id]: props }, { runDate: status.run_date, skated }).filter((b) => !/ ac$/.test(b)),
    saved: savedIds.has(id), onSave: VIEW_ONLY ? null : () => toggleSave(id) }));
  panel.prepend(el("button", { class: "close", "aria-label": "Close", text: "×", onclick: closePanel }));
  panel.classList.add("page");
  // Hazards as short chips; tap one for the full note.
  if ((d.hazards || []).length) {
    panel.append(el("div", { class: "hazards" }, ...d.hazards.map((h) =>
      el("details", { class: "hazard" }, el("summary", { text: "⚠ " + h.label }), el("p", { text: h.text })))));
  }
  // The graph tells the story: weather, water, ice, snow, and the clear images and reports.
  if (d.kind === "marsh") {
    // A marsh: no lake ice model or satellite reading; its colour is skaters' reports.
    panel.append(el("p", { class: "meta", text: "Marsh: colour comes from skaters' reports only." }));
  } else {
    const chart = el("div", { class: "wx-mount" });
    panel.append(chart);
    loadChart(id, chart);
  }
  if (d.warning) panel.append(el("p", { class: "warn", text: d.warning }));
  if (canLog()) panel.append(reportSection(id));
  if (WORKER_URL) panel.append(iceLogSection(id));
  if (d.patch_thumb) {
    // Grey ice next to black patches: shade the black part (open water or newer, thinner ice).
    panel.append(el("figure", { class: "patch" },
      el("img", { class: "thumb", src: "data/" + d.patch_thumb, alt: d.name + " satellite image with black patches shaded orange", loading: "lazy" }),
      el("figcaption", { text: "Orange: dark patches, maybe open water."
        + (d.patch_low_sun ? " Low sun: some may be mountain shadow." : "") })));
  }
  if (isOwner() && typeof d.browser_url === "string" && d.browser_url.startsWith("https://")) {
    panel.append(el("a", { class: "cop", href: d.browser_url, target: "_blank", rel: "noopener", text: "Open in Copernicus Browser" }));
  }
  if (VIEW_ONLY) {
    panel.hidden = false;
    return;
  }

  if (isOwner()) {
    const prow = el("div", { class: "row" });
    prow.append(el("button", {
      class: "act" + (d.hidden ? " on" : ""), text: d.hidden ? "Hidden (tap to show)" : "Hide",
      onclick: () => setPref(id, d.hidden ? "unhide" : "hide"),
    }));
    panel.append(prow);
  }
  panel.append(el("div", { class: "status", id: "status", text: statusText || (pending() ? pending() + " waiting to send" : "") }));
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
    if (s && s.day && mount.isConnected) renderWeatherChart(s, mount, chartMarkers(info(id)?.timeline));
  });
}

function setStatus(t) {
  const s = $("status");
  if (s) s.textContent = t;
}

// Everyone sees when the data is old; only the owner is told a job failed.
function showBanner() {
  const b = $("banner");
  if (status.stale_since) {
    b.textContent = isOwner()
      ? "Data from " + status.stale_since + " — the daily job failed."
      : "Last updated " + shortDate(status.stale_since) + ".";
    b.hidden = false;
  } else {
    b.hidden = true;
  }
}

function shortDay(iso) {
  const [y, m, dd] = iso.split("-").map(Number);
  return new Date(y, m - 1, dd).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function setupSearch() {
  const input = $("q");
  const list = $("results");
  let hits = [];
  let active = 0;
  const close = () => { list.hidden = true; list.replaceChildren(); input.setAttribute("aria-expanded", "false"); };
  const choose = (id) => {
    input.value = "";
    close();
    input.blur();
    if (!visible(id)) setFilter(defaults());
    closeTool();
    openLake(id, true);
  };
  const draw = () => {
    list.replaceChildren();
    if (!hits.length) {
      list.append(el("li", { class: "none", text: "No lake by that name" }));
    }
    hits.forEach((h, i) => {
      const d = info(h.id);
      const st = STYLE[d.label] || STYLE.unknown;
      const sw = el("i", { class: "sw" });
      sw.style.background = st.fill;
      sw.style.borderColor = st.line;
      const li = el("li", { role: "option", id: "opt-" + i, "aria-selected": String(i === active) },
        sw, el("span", { class: "nm", text: d.name }),
        el("span", { class: "sub", text: st.text }));
      li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(h.id); });
      list.append(li);
    });
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-activedescendant", hits.length ? "opt-" + active : "");
  };
  const sizes = {};
  for (const f of features) sizes[f.properties.id] = f.properties.area_acres;
  input.addEventListener("input", () => {
    const pool = {};
    for (const [id, d] of Object.entries(status.lakes)) {
      if (VIEW_ONLY && d.hidden) continue;
      pool[id] = { name: d.name, area_acres: sizes[id] };
    }
    hits = searchLakes(pool, input.value);
    active = 0;
    if (input.value.trim()) draw(); else close();
  });
  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { active = Math.min(active + 1, hits.length - 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); draw(); e.preventDefault(); }
    else if (e.key === "Enter" && hits[active]) { choose(hits[active].id); e.preventDefault(); }
    else if (e.key === "Escape") close();
  });
  input.addEventListener("blur", close);
}

function addKey() {
  const KEY_OPEN = "wildice.keyOpen";
  const ctl = L.control({ position: "topright" });
  ctl.onAdd = () => {
    const box = el("details", { class: "key" });
    let open = null;
    try { open = store.getItem(KEY_OPEN); } catch { /* storage blocked */ }
    box.open = open === null ? window.innerWidth >= 700 : open === "1";
    box.addEventListener("toggle", () => {
      try { store.setItem(KEY_OPEN, box.open ? "1" : "0"); } catch { /* storage blocked */ }
    });
    box.append(el("summary", { text: "Key" }));
    for (const [label] of KEY) {
      const s = STYLE[label];
      const sw = el("i", { class: "sw" });
      sw.style.background = s.fill;
      sw.style.borderColor = s.line;
      if (label === "likely_black_ice") sw.style.borderWidth = "3px";
      const row = el("div", { class: "key-row" });
      row.append(sw, el("b", { text: s.text })); // names only; the glossary explains each
      box.append(row);
    }
    if (!VIEW_ONLY) {
      const faded = el("div", { class: "key-row" });
      const fsw = el("i", { class: "sw" });
      fsw.style.cssText = "background:#3b82f6;border-color:#1d4ed8;opacity:.3";
      faded.append(fsw, el("span", { text: "Faded: hidden lake" }));
      box.append(faded);
      box.append(el("a", { class: "key-more", href: "#glossary", text: "Glossary" }));
    }
    L.DomEvent.disableClickPropagation(box);
    L.DomEvent.disableScrollPropagation(box);
    return box;
  };
  ctl.addTo(map);
}

function routeHash() {
  const code = inviteCodeFromHash(location.hash);
  if (code) {
    // Take the code out of the address bar and history straight away.
    history.replaceState(null, "", location.pathname + location.search);
    showInvite(code);
    return;
  }
  if (location.hash === "#review") { showReview(); return; }
  if (location.hash === "#glossary") { showGlossary(); return; }
  if (location.hash === "#account") { showAccount(); return; }
  if (location.hash === "#join") { showJoin(); return; }
  if (location.hash === "#skateable") { showTab("explore"); return; }
  const t = location.hash.match(/^#tab=(\w+)$/);
  if (t) { closePanel(); showTab(t[1]); return; }
  const m = location.hash.match(/^#lake=(.+)$/);
  if (!m) return;
  const id = decodeURIComponent(m[1]);
  if (info(id)) openLake(id, true);
}

function propsById() {
  const out = {};
  for (const f of features) out[f.properties.id] = f.properties;
  return out;
}

const TABS = ["explore", "map", "mine", "upload"];
let tab = "explore";
let skated = null; // Set of lake ids this phone's skater has skated, or null (not joined / not loaded)
let skatedRows = null;
let savedIds = new Set();

async function loadMine() {
  const [sv, sk] = await Promise.all([getSaved(ICELOG), getDevice(store) ? getSkated(ICELOG) : Promise.resolve(null)]);
  savedIds = new Set(sv);
  markSaved();
  skatedRows = sk;
  skated = sk ? new Set(sk.map((r) => r.lake_id)) : null;
  renderTab();
}

// Flip just the Save button: re-rendering the page would reload Field Notes and lose
// the scroll position.
function paintSave(id) {
  const b = currentId === id ? $("panel").querySelector("button.save") : null;
  if (!b) return;
  const on = savedIds.has(id);
  b.classList.toggle("on", on);
  b.setAttribute("aria-pressed", String(on));
  b.textContent = on ? "♥ Saved" : "♡ Save";
}

// This viewer's own saved lakes come first in Explore (no stars anywhere).
function markSaved() {
  for (const [id, d] of Object.entries(status.lakes)) d.pinned = !VIEW_ONLY && savedIds.has(id);
  if (map) build();
}

async function toggleSave(id) {
  const on = !savedIds.has(id);
  on ? savedIds.add(id) : savedIds.delete(id);
  markSaved();
  paintSave(id);
  const ok = await setSaved(id, on, ICELOG);
  if (!ok) {
    on ? savedIds.delete(id) : savedIds.add(id);
    markSaved();
    paintSave(id);
    showMsg("Couldn't save, try again");
  }
  if (tab === "mine") renderTab();
}


function photoUrl(d) {
  // A skater's featured photo first, then the uncut satellite photo of the lake and
  // its surroundings. The lake-shaped thumbnail is for the checks, not for people.
  if (d.featured_photo && WORKER_URL) return `${WORKER_URL}/api/photos/${encodeURIComponent(d.featured_photo)}`;
  return d.photo ? "data/" + d.photo : "";
}

function renderTab() {
  if (tab === "explore") {
    const tripLoad = { ...tripOpts(true), load: () => loadFeed(ICELOG) };
    renderExplore($("explore-view"), {
      status, props: propsById(), ctx: { runDate: status.run_date, skated },
      onMap: () => { setFilter({ ...mapFilter, labels: [...SKATE] }); showTab("map"); },
      onSeason: (label) => { setFilter({ ...defaults(), labels: [label] }); showTab("map"); },
      openLake: (id) => openLake(id, true), photoUrl,
      styleOf: (l) => STYLE[l] || STYLE.unknown,
      geometry: (id) => layers.get(id)?.feature.geometry || null,
      saved: [...savedIds],
      here: () => here,
      locate: () => {
        if (!navigator.geolocation) return;
        navigator.geolocation.getCurrentPosition((pos) => { here = { lat: pos.coords.latitude, lon: pos.coords.longitude }; renderTab(); },
          () => showMsg("Location is off."), { maximumAge: 600000, timeout: 15000 });
      },
      renderTrips: (mount, limit) => renderTrips(mount, tripLoad, limit),
      openTrips: () => { const box = el("div", { class: "trips-box" }); openPage("Trip reports", box); renderTrips(box, tripLoad); },
    });
  } else if (tab === "mine") {
    renderMine($("mine-view"), { glossaryHref: "#glossary", status, saved: [...savedIds], skated: skatedRows, joined: !!getDevice(store),
      labelText: (l) => (STYLE[l] || STYLE.unknown).text, openLake: (id) => openLake(id, true) });
  } else if (tab === "upload") {
    renderUpload($("upload-view"), { joined: canLog(), features: [...features, ...spotFeatures], storage: store,
      sharedLink: takeShared(),
      strava: STRAVA_CLIENT_ID ? {
        status: () => strava.status(ICELOG), activities: () => strava.activities(ICELOG),
        points: (id) => strava.points(id, ICELOG), disconnect: () => strava.disconnect(ICELOG),
        authorize: stravaAuthorize,
      } : null,
      resolveLink: async (url) => {
        const r = await fetch(`${WORKER_URL}/api/resolve-link?url=${encodeURIComponent(url)}`);
        return r.ok ? (await r.json()).url : null;
      },
      addSpot: async (sp) => {
        const r = await addSpot(sp, ICELOG);
        if (r.ok && !status.lakes[r.id]) {
          addSpots([{ id: r.id, name: r.name, kind: r.kind, lat: sp.lat, lon: sp.lon, bbox: sp.bbox, added_by: getDevice(store)?.name, last_report: null }]);
          build();
        }
        return r;
      },
      queue: (r) => { queueReport(store, r); sendQueue(); setTimeout(loadMine, 4000); },
      onJoin: () => { location.hash = "#join"; } });
  }
}

function showTab(name) {
  tab = TABS.includes(name) ? name : "explore";
  if (tab !== "upload") sharedLink = null;
  $("explore-view").hidden = tab !== "explore";
  $("mine-view").hidden = tab !== "mine";
  $("upload-view").hidden = tab !== "upload";
  $("map").classList.toggle("off", tab !== "map");
  document.body.dataset.tab = tab;
  for (const b of document.querySelectorAll("#tabs button")) b.setAttribute("aria-current", b.dataset.tab === tab ? "page" : "false");
  if (tab === "map") map.invalidateSize();
  renderTab();
}

function isOwner() { return !VIEW_ONLY && WORKER_URL && getDevice(store)?.role === "owner"; }

async function setPref(id, action) {
  const d = info(id);
  const before = { pinned: d.pinned, hidden: d.hidden };
  if (action === "pin" || action === "unpin") d.pinned = action === "pin";
  else d.hidden = action === "hide";
  build();
  renderPanel(id, "Saving…");
  const r = await ownerCall("/api/prefs", { ...ICELOG, method: "POST", body: { lake_id: id, action } }).catch(() => null);
  if (!r || r.status !== 200) {
    Object.assign(d, before);
    build();
  }
  if (currentId === id) renderPanel(id, r && r.status === 200 ? "Saved: the map updates after the next daily run" : "Couldn't save, try again");
}

function showAccount() {
  const page = openPage("Account", el("p", { class: "meta", text: "Loading…" }));
  page.classList.add("page");
  const body = el("div");
  page.lastChild.replaceWith(body);
  renderAccount(body, {
    ICELOG, lakeName: (id) => info(id)?.name || id, joinSection: joinPrompt("Join to post reports, comments and photos."),
    openLake: (id) => openLake(id, true),
    onChanged: () => paintMe(),
    onSignedOut: () => { savedIds = new Set(); skated = null; markSaved(); paintMe(); closePanel(); showMsg("Signed out on this phone."); renderTab(); },
  });
}

// The round picture at the top right: your photo or initial; opens the account page.
async function paintMe() {
  const btn = $("me-btn");
  if (!btn) return;
  const d = getDevice(store);
  let avatar = null;
  if (d && WORKER_URL) {
    const r = await account.me(ICELOG).catch(() => null);
    if (r && r.status === 200) avatar = r.data.avatar;
  }
  btn.replaceChildren(avatarEl(avatarUrl(WORKER_URL, avatar), d ? d.name : "", 28));
  btn.setAttribute("aria-label", d ? `Account: ${d.name}` : "Account and invites");
}

function showGlossary() {
  openPage("Glossary", ...GLOSSARY.map((sec) => el("section", { class: "glossary" }, el("h3", { text: sec.title }),
    el("dl", {}, ...sec.items.flatMap((i) => [el("dt", { text: i.term }), el("dd", { text: i.text })])))));
}

function openPage(title, ...kids) {
  currentId = null;
  const panel = $("panel");
  panel.classList.remove("page");
  panel.replaceChildren(
    el("button", { class: "close", "aria-label": "Close", text: "×", onclick: closePanel }),
    el("h2", { text: title }), ...kids.filter(Boolean));
  panel.hidden = false;
  return panel;
}

function showInvite(code) {
  if (!WORKER_URL) { showMsg("Reports aren't set up yet."); return; }
  const decision = inviteDecision(getDevice(store));
  if (decision === "refuse") {
    // Never let an invite (e.g. one being tested) replace the owner's key on this phone.
    openPage("Invite link", el("p", { text: "This phone is the owner's. Send the link to someone else." }));
    return;
  }
  if (decision === "confirm" && !confirm("This phone is already signed in to Wild Ice. Join again with this new link?")) return;
  const name = el("input", { type: "text", maxlength: "40", placeholder: "Your name", "aria-label": "Your name" });
  const msg = el("p", { class: "status" });
  const form = el("form", { class: "comment-form" },
    el("p", { class: "meta", text: "You're invited to Wild Ice." }),
    el("p", { class: "disc", text: "Conditions are estimates. Check the ice yourself." }),
    name, el("button", { class: "act", type: "submit", text: "Join" }), msg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "Joining…";
    const r = await redeemInvite(code, name.value.trim(), ICELOG);
    if (!r.ok) { msg.textContent = r.error; return; }
    openPage("You're in", el("p", { text: `Welcome, ${r.name}. Tap a lake to log the ice.` }));
  });
  openPage("Join Wild Ice", form);
  name.focus();
}

async function showReview() {
  if (!isOwner()) { showMsg("Review is for the owner's phone."); return; }
  const body = el("div", { class: "review" });
  openPage("Review", body);
  const r = await ownerCall("/api/review", ICELOG).catch(() => null);
  if (!r || r.status !== 200) { body.append(el("p", { class: "status", text: "Couldn't load the review list." })); return; }
  const { comments, photos, friends } = r.data;
  const stats = el("section", { class: "stats" });
  body.append(stats);
  ownerCall("/api/stats", ICELOG).then((sr) => {
    if (!sr || sr.status !== 200) return;
    const d = sr.data;
    const plat = Object.entries(d.installs.by_platform).map(([k, v]) => `${v} ${({ ios: "iPhone", android: "Android", desktop: "computer", other: "other" })[k] || k}`).join(" · ");
    const tile = (n, t) => el("div", { class: "stat" }, el("b", { text: String(n) }), el("span", { text: t }));
    stats.append(el("h3", { text: "Numbers" }),
      el("div", { class: "stat-row" },
        tile(d.installs.total, "installed"), tile(d.installs.active_7d, "opened this week"),
        tile(d.members.total, "members"), tile(d.get_app_clicks.d30, "Get the app taps, 30 days")),
      el("p", { class: "meta", text: [plat, `${d.installs.new_7d} new installs and ${d.members.new_7d} new members this week`,
        `${d.reports_30d} reports in 30 days`].filter(Boolean).join(" · ") }),
      el("p", { class: "meta", text: "Anonymous." }));
  }).catch(() => {});
  const decide = (path, action, row) => async () => {
    row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    const res = await ownerCall(path, { ...ICELOG, method: "POST", body: { action } }).catch(() => null);
    row.replaceChildren(el("p", { class: "meta", text: res && res.status === 200 ? "Done: " + action : "Failed, try again" }));
  };
  const lakeName = (id) => (info(id) ? info(id).name : id);
  body.append(el("h3", { text: `Waiting comments (${comments.length})` }));
  for (const c of comments) {
    const row = el("div", { class: "review-row" });
    row.append(el("p", {}, el("b", { text: c.name }), el("span", { class: "meta", text: " on " + lakeName(c.lake_id) })),
      el("p", { text: c.text }),
      el("div", { class: "row" },
        el("button", { class: "act", text: "Approve", onclick: decide(`/api/review/comments/${c.id}`, "approve", row) }),
        el("button", { class: "act", text: "Reject", onclick: decide(`/api/review/comments/${c.id}`, "reject", row) })));
    body.append(row);
  }
  const spots = Object.entries(status.lakes).filter(([, d]) => d.spot);
  if (spots.length) {
    body.append(el("h3", { text: `Spots (${spots.length})` }));
    for (const [sid, d] of spots) {
      const row = el("div", { class: "review-row" });
      row.append(el("p", {}, el("b", { text: d.name }), el("span", { class: "meta", text: ` · ${SPOT_KIND[d.kind] || "Spot"} · added by ${d.added_by || "?"}` })),
        el("div", { class: "row" },
          el("button", { class: "act", text: "Open", onclick: () => openLake(sid, true) }),
          el("button", { class: "act", text: "Hide (spam or duplicate)", onclick: decide(`/api/spots/${sid}/hide`, "hide", row) })));
      body.append(row);
    }
  }
  body.append(el("h3", { text: `New photos (${photos.length})` }),
    el("p", { class: "meta", text: "Already public." }));
  for (const p of photos) {
    const row = el("div", { class: "review-row" });
    const img = el("img", { class: "thumb", alt: "Photo from " + (p.credit || "a friend") });
    // <img> can't send the owner key, so fetch the waiting photo and show it from memory.
    fetch(`${WORKER_URL}/api/photos/${encodeURIComponent(p.public_id)}`, { headers: { Authorization: `Bearer ${getDevice(store).key}` } })
      .then((res) => (res.ok ? res.blob() : null)).then((b) => { if (b) img.src = URL.createObjectURL(b); }).catch(() => {});
    row.append(img, el("p", { class: "meta", text: `${p.credit || "A friend"} · ${lakeName(p.lake_id)} · ${shortDay(p.created_at.slice(0, 10))}` }),
      el("div", { class: "row" },
        el("button", { class: "act", text: "Feature", onclick: decide(`/api/review/photos/${p.id}`, "feature", row) }),
        el("button", { class: "act", text: "Remove", onclick: decide(`/api/review/photos/${p.id}`, "reject", row) })));
    body.append(row);
  }
  const out = el("div", {});
  const { reports = [], published = [], featured = [] } = r.data;
  body.append(el("h3", { text: `Recent reports (${reports.length})` }));
  for (const rep of reports) {
    const row = el("div", { class: "review-row" });
    row.append(el("p", {}, el("b", { text: rep.credit || "Someone" }),
        el("span", { class: "meta", text: ` · ${lakeName(rep.lake_id)} · ${shortDay(rep.day)}` })),
      el("p", { text: (REPORT[rep.rating] ? REPORT[rep.rating].text : rep.rating) + (rep.grade ? " " + rep.grade : "") + (rep.note ? " — " + rep.note : "") }),
      el("button", { class: "act", text: "Remove", onclick: decide(`/api/review/reports/${rep.id}`, "remove", row) }));
    body.append(row);
  }
  body.append(el("h3", { text: `Published comments (${published.length})` }));
  for (const c of published) {
    const row = el("div", { class: "review-row" });
    row.append(el("p", {}, el("b", { text: c.name }), el("span", { class: "meta", text: " on " + lakeName(c.lake_id) })),
      el("p", { text: c.text }),
      el("button", { class: "act", text: "Take down", onclick: decide(`/api/review/comments/${c.id}`, "remove", row) }));
    body.append(row);
  }
  body.append(el("h3", { text: `Featured photos (${featured.length})` }));
  for (const p of featured) {
    const row = el("div", { class: "review-row" });
    row.append(el("img", { class: "thumb", src: `${WORKER_URL}/api/photos/${encodeURIComponent(p.public_id)}`, alt: "Featured photo", loading: "lazy" }),
      el("p", { class: "meta", text: `${p.credit || "A friend"} · ${lakeName(p.lake_id)}` }),
      el("button", { class: "act", text: "Take down", onclick: decide(`/api/review/photos/${p.id}`, "remove", row) }));
    body.append(row);
  }
  body.append(el("h3", { text: "Friends" }));
  for (const f of friends) {
    const row = el("div", { class: "review-row friend" });
    row.append(el("span", { text: f.name + (f.role === "owner" ? " (you)" : "") + (f.revoked ? " — switched off" : "") }));
    if (f.role !== "owner" && !f.revoked) {
      row.append(el("button", { class: "act", text: "New phone link", onclick: async () => {
        const res = await ownerCall("/api/invites", { ...ICELOG, method: "POST", body: { friend_id: f.id } }).catch(() => null);
        if (res && res.status === 200) showInviteLink(out, res.data.invite_url, `New-phone link for ${f.name}. It works once.`);
      } }));
      row.append(el("button", { class: "act", text: "Switch off", onclick: async () => {
        if (!confirm(`Switch off ${f.name}'s invite? Their phone stops working; past reports stay.`)) return;
        const res = await ownerCall(`/api/friends/${f.id}/revoke`, { ...ICELOG, method: "POST", body: {} }).catch(() => null);
        row.replaceChildren(el("span", { text: res && res.status === 200 ? f.name + " — switched off" : "Failed, try again" }));
      } }));
    }
    body.append(row);
  }
  body.append(el("button", { class: "act", text: "New invite", onclick: async () => {
    const res = await ownerCall("/api/invites", { ...ICELOG, method: "POST", body: {} }).catch(() => null);
    if (!res || res.status !== 200) { out.replaceChildren(el("p", { class: "status", text: "Couldn't make an invite." })); return; }
    showInviteLink(out, res.data.invite_url, "Send this to one friend. It works once, on one phone.");
  } }), out);
}

function showInviteLink(out, url, text) {
  const link = el("input", { type: "text", readonly: "", value: url, "aria-label": "Invite link" });
  out.replaceChildren(el("p", { class: "meta", text }), link,
    el("button", { class: "act", text: "Copy", onclick: () => navigator.clipboard?.writeText(url) }));
  out.scrollIntoView({ block: "nearest" });
}

async function load() {
  const [g, s] = await Promise.all([
    fetch("data/lakes.geojson").then((r) => { if (!r.ok) throw new Error("lakes"); return r.json(); }),
    fetch("data/status.json").then((r) => { if (!r.ok) throw new Error("status"); return r.json(); }),
  ]);
  features = g.features;
  status = s;
  // Pins are personal: the public map shows every lake the same way.
  if (VIEW_ONLY) for (const d of Object.values(status.lakes)) d.pinned = false;
}

async function main() {
  map = L.map("map").setView([61.2, -149.5], 8);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "&copy; OpenStreetMap contributors · lake depths: <a href=\"https://www.hydrosheds.org/products/hydrolakes\">HydroLAKES</a> (CC BY 4.0)",
  }).addTo(map);
  addKey();
  addMapTools();
  window.addEventListener("hashchange", routeHash);
  if (VIEW_ONLY) {
    document.body.classList.add("embed");
    twoFingerMap();
    // A strip under the host site's header pointing to the full app (opens outside the embed).
    const app = location.origin + location.pathname;
    $("bar").before(el("div", { id: "promo" },
      el("a", { class: "promo-brand", href: app, target: "_blank", rel: "noopener" },
        el("img", { src: "icons/icon-192.png", alt: "", width: "44", height: "44" }),
        el("span", { class: "promo-text" }, el("b", { text: "Wild Ice" }),
          el("span", { text: "Lake ice, mapped by skaters." }))),
      el("a", { class: "promo-btn", href: app + "#join", target: "_blank", rel: "noopener", text: "Get the app",
        onclick: () => countUse("/api/tally", { name: "get_app_click" }) })));
  } else {
    window.addEventListener("pagehide", commitReport); // don't lose a report in its undo window
    pingInstall();
  window.addEventListener("online", sendQueue);
  const dropped = clearLegacy(store); // the old GitHub token never stays on a phone
  if (dropped) showMsg(`${dropped} old unsent change(s) from an older version were dropped.`);
  if (WORKER_URL) {
    checkDevice(ICELOG).then((state) => {
      if (state === "revoked") {
        showMsg("This invite was switched off.");
        build();
        if (currentId && !$("panel").hidden) renderPanel(currentId);
      } else {
        sendQueue(); // reports logged without signal go out now
      }
    });
  }
  }
  try {
    await load();
  } catch {
    showMsg("Could not load lake data.");
    return;
  }
  if (WORKER_URL) await loadSpots(ICELOG).then(addSpots).catch(() => { /* spots are extra */ });
  showBanner();
  $("msg").addEventListener("click", () => { $("msg").hidden = true; });
  if ("serviceWorker" in navigator && !VIEW_ONLY) navigator.serviceWorker.register("sw.js").catch(() => { /* still works as a site */ });
  paintInstall();
  if (!VIEW_ONLY) overlayReported();
  build();
  setupSearch();
  if (!VIEW_ONLY) {
    for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => {
      closePanel();
      history.replaceState(null, "", "#tab=" + b.dataset.tab);
      showTab(b.dataset.tab);
    });
    if (sharedLink) history.replaceState(null, "", location.pathname + "#tab=upload");
    const fromStrava = await stravaReturn();
    showTab(sharedLink || fromStrava ? "upload" : location.hash.startsWith("#lake=") ? "map" : "explore");
    loadMine();
    if (WORKER_URL) {
      const me = el("a", { id: "me-btn", href: "#account", class: "me-btn" });
      $("bar").prepend(me);
      paintMe();
    }
  }
  routeHash();
}

main();
