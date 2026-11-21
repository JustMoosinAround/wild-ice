import { renderWeatherChart } from "./chart.js";
import { searchLakes } from "./search.js";
import { skateableLakes } from "./skatelist.js";
import {
  GRADES, flushReports, getDevice, inviteCodeFromHash, loadLake, ownerCall, postComment, prepPhoto,
  queueReport, queuedReports, redeemInvite, makeReport, checkDevice, clearLegacy, inviteDecision,
} from "./icelog.js";
import { TURNSTILE_SITEKEY, WORKER_URL } from "./config.js";

const STYLE = {
  open_water: { fill: "#3b82f6", line: "#1d4ed8", text: "Open water" },
  freezing: { fill: "#14b8a6", line: "#0f766e", text: "Freezing" },
  likely_black_ice: { fill: "#0f172a", line: "#facc15", text: "Likely black ice" },
  rough_ice: { fill: "#78716c", line: "#facc15", text: "Skateable, rough" },
  snow_covered: { fill: "#f8fafc", line: "#6b7280", text: "Snow covered" },
  unknown: { fill: "#9ca3af", line: "#6b7280", text: "Unknown" },
};
// Map key, best skating first.
const KEY = [
  ["likely_black_ice", "Thick enough to skate, little snow, and a satellite sees ice"],
  ["rough_ice", "Someone skated it but graded the ice D or worse"],
  ["freezing", "Ice forming, still too thin to skate"],
  ["unknown", "Thick enough, but no clear satellite look yet"],
  ["snow_covered", "Snow on the ice"],
  ["open_water", "No ice yet"],
];
const SKATE_LABELS = new Set(["likely_black_ice", "rough_ice", "freezing"]);
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
  const d = info(id);
  if (VIEW_ONLY && d && d.hidden) return false;
  if (!$("only-skate").checked) return true;
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
      box.append(el("p", { class: "report-msg", text: what + ": add details" }), detailsForm(id, p));
    }
    return box;
  }
  const mine = d.reported && d.reported.day === todayLocal() ? d.reported : null;
  box.append(el("p", { class: "report-head", text: mine
    ? "You logged " + REPORT[mine.rating].text.toLowerCase() + " today. Changed?"
    : "Log the ice: how is it?" }));
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
  box.append(grid);
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
    form.append(el("p", { class: "meta", text: "Ice quality (optional): A+ best … F- skateable but awful" }), chips);
  }
  const note = el("input", { type: "text", placeholder: "What did you see? (only you see notes)", "aria-label": "Note", maxlength: "300" });
  note.value = p.note || "";
  note.addEventListener("input", () => { p.note = note.value; });
  const photo = el("input", { type: "file", accept: "image/jpeg,image/*", "aria-label": "Photo" });
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
  form.append(note, el("label", { class: "meta", text: "Photo (optional)" }), photo, photoMsg);
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
    form.append(el("p", { class: "meta", text: "At the lake? Adding your location confirms which lake." }), where);
  }
  form.append(el("button", { class: "act", type: "submit", text: "Log the ice" }));
  form.addEventListener("submit", (e) => { e.preventDefault(); p.note = note.value.trim(); commitReport(); });
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
  queueReport(store, makeReport({ lakeId: p.id, rating: p.rating, grade: p.grade, note: p.note,
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

// Public part of the Ice Log: featured photos and comments, for everyone.
function iceLogSection(id) {
  const box = el("section", { class: "icelog", "aria-label": "Ice Log" });
  box.append(el("h3", { text: "Ice Log" }));
  const photos = el("div", { class: "featured" });
  const list = el("ol", { class: "comments" });
  box.append(photos, el("p", { class: "disc", text: status.disclaimer || "Rough estimate only — check ice yourself." }), list, commentForm(id, list));
  loadLake(id, ICELOG).then(({ comments, photos: ph }) => {
    if (!box.isConnected) return;
    for (const p of ph || []) {
      photos.append(el("figure", {},
        el("img", { src: `${WORKER_URL}/api/photos/${encodeURIComponent(p.public_id)}`, alt: "Photo of the lake", loading: "lazy" }),
        el("figcaption", { text: (p.credit || "A skater") + ", " + shortDay(p.created_at.slice(0, 10)) })));
    }
    if (!comments.length) list.append(el("li", { class: "meta", text: "No comments yet." }));
    for (const c of comments) {
      list.append(el("li", {}, el("b", { text: c.name }), el("span", { class: "meta", text: " · " + shortDay(c.created_at.slice(0, 10)) }), el("p", { text: c.text })));
    }
  });
  return box;
}

function commentForm(id, list) {
  const device = getDevice(store);
  const form = el("form", { class: "comment-form" });
  const name = el("input", { type: "text", placeholder: "Your name", "aria-label": "Your name", maxlength: "40", required: "" });
  if (device) name.value = device.name;
  const text = el("textarea", { placeholder: "Tips for other skaters (no links)", "aria-label": "Comment", maxlength: "500", rows: "3", required: "" });
  const msg = el("p", { class: "status" });
  const human = el("div", { class: "turnstile" });
  let token = null;
  form.append(name, text);
  if (!device) {
    form.append(human, el("p", { class: "meta", text: "Comments are checked before they appear." }));
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
  const s = STYLE[d.label] || STYLE.unknown;
  const panel = $("panel");
  panel.replaceChildren();
  panel.append(el("button", { class: "close", "aria-label": "Close", text: "×", onclick: closePanel }));
  panel.append(el("h2", { text: (d.pinned ? "★ " : "") + d.name }));
  const props = (layers.get(id) || {}).feature?.properties || {};
  if (props.area_acres) {
    let size = Math.round(props.area_acres).toLocaleString() + " acres";
    if (props.depth_m) size += ", about " + Math.round(props.depth_m) + " m deep on average (HydroLAKES estimate)";
    panel.append(el("p", { class: "meta", text: size }));
  }
  const chip = el("span", { class: "chip", text: s.text });
  chip.style.background = s.fill;
  chip.style.borderColor = s.line;
  chip.style.color = ["snow_covered", "unknown"].includes(d.label) ? "#0f172a" : "#fff";
  panel.append(el("div", {}, chip, el("span", { class: "meta", text: "  " + d.confidence + " confidence" })));
  panel.append(el("p", { class: "meta", text: d.reason }));
  if (d.warning) panel.append(el("p", { class: "warn", text: d.warning }));
  if (canLog()) panel.append(reportSection(id));
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
  if (d.patch_thumb) {
    // Grey ice next to black patches: shade the black part (open water or newer, thinner ice).
    panel.append(el("figure", { class: "patch" },
      el("img", { class: "thumb", src: "data/" + d.patch_thumb, alt: d.name + " satellite image with black patches shaded orange", loading: "lazy" }),
      el("figcaption", { text: "Orange: black patches next to grey ice. Could be open water or newer, thinner ice: check before you cross."
        + (d.patch_low_sun ? " Low sun: some may be mountain shadow." : "") })));
  } else if (d.thumb) {
    panel.append(el("img", { class: "thumb", src: "data/" + d.thumb, alt: d.name + " satellite thumbnail", loading: "lazy" }));
  }
  if (typeof d.browser_url === "string" && d.browser_url.startsWith("https://")) {
    panel.append(el("a", { class: "cop", href: d.browser_url, target: "_blank", rel: "noopener", text: "Open in Copernicus Browser" }));
  }
  if (WORKER_URL) panel.append(iceLogSection(id));
  if (VIEW_ONLY) {
    panel.hidden = false;
    return;
  }

  if (isOwner()) {
    const prow = el("div", { class: "row" });
    prow.append(el("button", {
      class: "act" + (d.pinned ? " on" : ""), text: d.pinned ? "★ Pinned" : "Pin",
      onclick: () => setPref(id, d.pinned ? "unpin" : "pin"),
    }));
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
    if (s && s.day && mount.isConnected) renderWeatherChart(s, mount);
  });
}

function setStatus(t) {
  const s = $("status");
  if (s) s.textContent = t;
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
    if (!visible(id)) { $("only-skate").checked = false; applyFilter(); }
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
        sw, el("span", { class: "nm", text: (d.pinned ? "★ " : "") + d.name }),
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
    if (!VIEW_ONLY) {
      const star = el("div", { class: "key-row" });
      star.append(el("i", { class: "star", text: "★" }), el("span", { text: "Pinned lake" }));
      box.append(star);
      const faded = el("div", { class: "key-row" });
      const fsw = el("i", { class: "sw" });
      fsw.style.cssText = "background:#3b82f6;border-color:#1d4ed8;opacity:.3";
      faded.append(fsw, el("span", { text: "Faded: hidden lake" }));
      box.append(faded);
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
  if (location.hash === "#skateable") { showSkateable(); return; }
  const m = location.hash.match(/^#lake=(.+)$/);
  if (!m) return;
  const id = decodeURIComponent(m[1]);
  if (info(id)) openLake(id, true);
}

function areaById() {
  const out = {};
  for (const f of features) out[f.properties.id] = f.properties.area_acres;
  return out;
}

// Every lake that looks skateable today, best first; tap one to open it.
function showSkateable() {
  const list = skateableLakes(status.lakes, areaById());
  const items = el("ol", { class: "skate-list" });
  for (const d of list) {
    const s = STYLE[d.label] || STYLE.unknown;
    const sw = el("i", { class: "sw" });
    sw.style.background = s.fill;
    sw.style.borderColor = s.line;
    const est = d.thickness_cm != null ? `~${d.thickness_cm} cm · ` : "";
    items.append(el("li", {}, el("button", { type: "button", class: "skate-row", onclick: () => openLake(d.id, true) },
      sw, el("span", { class: "nm" }, el("b", { text: (d.pinned ? "★ " : "") + d.name }),
        el("span", { class: "meta", text: est + s.text + " · " + d.confidence + " confidence" })))));
  }
  openPage(list.length ? `Skateable today (${list.length})` : "Nothing looks skateable today",
    el("p", { class: "disc", text: status.disclaimer || "Rough estimate only — check ice yourself." }), items);
}

function addSkateButton() {
  const n = skateableLakes(status.lakes, areaById()).length;
  if (!n) return;
  $("bar").append(el("a", { class: "review-link", href: "#skateable", text: `Skateable (${n})` }));
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

function openPage(title, ...kids) {
  currentId = null;
  const panel = $("panel");
  panel.replaceChildren(
    el("button", { class: "close", "aria-label": "Close", text: "×", onclick: closePanel }),
    el("h2", { text: title }), ...kids);
  panel.hidden = false;
  return panel;
}

function showInvite(code) {
  if (!WORKER_URL) { showMsg("The Ice Log isn't set up yet."); return; }
  const decision = inviteDecision(getDevice(store));
  if (decision === "refuse") {
    // Never let an invite (e.g. one being tested) replace the owner's key on this phone.
    openPage("Invite link", el("p", { text: "This phone is already the owner's. Send the link to the friend it's for." }));
    return;
  }
  if (decision === "confirm" && !confirm("This phone is already signed in to the Ice Log. Join again with this new link?")) return;
  const name = el("input", { type: "text", maxlength: "40", placeholder: "Your name", "aria-label": "Your name" });
  const msg = el("p", { class: "status" });
  const form = el("form", { class: "comment-form" },
    el("p", { class: "meta", text: "You're invited to the Wild Ice Ice Log. Your name shows on your comments and on photos the owner features. This invite works once, on this phone." }),
    name, el("button", { class: "act", type: "submit", text: "Join" }), msg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    msg.textContent = "Joining…";
    const r = await redeemInvite(code, name.value.trim(), ICELOG);
    if (!r.ok) { msg.textContent = r.error; return; }
    openPage("You're in", el("p", { text: `Welcome, ${r.name}. Tap a lake to log the ice.` }));
  });
  openPage("Join the Ice Log", form);
  name.focus();
}

async function showReview() {
  if (!isOwner()) { showMsg("Review is for the owner's phone."); return; }
  const body = el("div", { class: "review" });
  openPage("Review", body);
  const r = await ownerCall("/api/review", ICELOG).catch(() => null);
  if (!r || r.status !== 200) { body.append(el("p", { class: "status", text: "Couldn't load the review list." })); return; }
  const { comments, photos, friends } = r.data;
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
  body.append(el("h3", { text: `Waiting photos (${photos.length})` }));
  for (const p of photos) {
    const row = el("div", { class: "review-row" });
    const img = el("img", { class: "thumb", alt: "Photo from " + (p.credit || "a friend") });
    // <img> can't send the owner key, so fetch the waiting photo and show it from memory.
    fetch(`${WORKER_URL}/api/photos/${encodeURIComponent(p.public_id)}`, { headers: { Authorization: `Bearer ${getDevice(store).key}` } })
      .then((res) => (res.ok ? res.blob() : null)).then((b) => { if (b) img.src = URL.createObjectURL(b); }).catch(() => {});
    row.append(img, el("p", { class: "meta", text: `${p.credit || "A friend"} · ${lakeName(p.lake_id)} · ${shortDay(p.created_at.slice(0, 10))}` }),
      el("div", { class: "row" },
        el("button", { class: "act", text: "Feature", onclick: decide(`/api/review/photos/${p.id}`, "feature", row) }),
        el("button", { class: "act", text: "Reject", onclick: decide(`/api/review/photos/${p.id}`, "reject", row) })));
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
      el("button", { class: "act", text: "Remove (wrong or bad report)", onclick: decide(`/api/review/reports/${rep.id}`, "remove", row) }));
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
  $("only-skate").addEventListener("change", applyFilter);
  window.addEventListener("hashchange", routeHash);
  if (VIEW_ONLY) {
    document.body.classList.add("embed");
  } else {
    window.addEventListener("pagehide", commitReport); // don't lose a report in its undo window
  if (isOwner()) {
    $("bar").append(el("a", { class: "review-link", href: "#review", text: "Review" }));
  }
  window.addEventListener("online", sendQueue);
  const dropped = clearLegacy(store); // the old GitHub token never stays on a phone
  if (dropped) showMsg(`${dropped} old unsent change(s) from before the Ice Log were dropped.`);
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
  showBanner();
  if (!VIEW_ONLY) overlayReported();
  build();
  setupSearch();
  addSkateButton();
  routeHash();
}

main();
