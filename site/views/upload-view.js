// Upload tab: GPX / FIT (.gz) tracks become trip reports. Each file is read on the
// phone, matched to catalog lakes, and sent as lake + day + minutes + one point.
import { shortDate } from "../explore.js";
import { GRADES, makeReport } from "../icelog.js";
import { TrackError, matchLakes, readTrackFile, trackSummary } from "../track.js";
import { parseActivityLink } from "../activitylink.js";

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

// From Strava or Garmin Connect without hunting for the export: paste the activity's
// link (Share -> Copy link in the app; on Android, Share -> Wild Ice fills it in), and
// the service's own GPX download opens. Then pick the file below.
function linkBox(opts) {
  const input = el("input", { type: "url", placeholder: "Paste a Strava or Garmin activity link", "aria-label": "Activity link" });
  const out = el("div", { class: "link-out" });
  const go = async () => {
    let a = parseActivityLink(input.value);
    if (a && a.short) {
      out.replaceChildren(el("p", { class: "meta", text: "Opening the link…" }));
      const full = await opts.resolveLink(a.short).catch(() => null);
      a = full ? parseActivityLink(full) : null;
    }
    if (!a || a.short) {
      out.replaceChildren(el("p", { class: "warn", text: "That doesn't look like a Strava or Garmin Connect activity link." }));
      return;
    }
    const how = a.service === "Strava" ? "⋯ (top right) → Export GPX" : "⚙ (top right) → Export to GPX";
    out.replaceChildren(
      el("a", { class: "act file-label", href: a.gpxUrl, target: "_blank", rel: "noopener", text: `⇩ Download the GPX from ${a.service}` }),
      el("p", { class: "meta", text: `Sign in to ${a.service} in your browser if it asks. When the file has downloaded, come back and tap Choose track files.` }),
      el("p", { class: "meta" }, "No file? ", el("a", { href: a.pageUrl, target: "_blank", rel: "noopener", text: "Open the activity" }), ` on the website and use ${how}.`));
  };
  input.addEventListener("change", go);
  if (opts.sharedLink) { input.value = opts.sharedLink; setTimeout(go, 0); }
  return el("section", { class: "upload-card" }, el("b", { text: "From Strava or Garmin" }),
    el("p", { class: "meta", text: "In the app, tap Share → Copy link on your skate, and paste it here." }),
    el("div", { class: "report-note" }, input, el("button", { type: "button", class: "act small", text: "Get the GPX", onclick: go })), out);
}

// Connect Strava: pick a recent activity, no file. Its minutes and track are shown only to you.
function stravaBox(opts, list) {
  const box = el("section", { class: "upload-card" }, el("b", { text: "Strava" }), el("p", { class: "meta", text: "Checking…" }));
  const S = opts.strava;
  (async () => {
    const st = await S.status().catch(() => null);
    if (!st || st.status !== 200 || !st.data.available) { box.remove(); return; }
    if (!st.data.connected) {
      box.replaceChildren(el("b", { text: "Strava" }),
        el("p", { class: "meta", text: "Connect once, then pick a recent skate: no file to download. Your track and minutes stay private; only what you write in the trip report is shown to others." }),
        el("button", { type: "button", class: "act strava-btn", text: "Connect with Strava", onclick: S.authorize }));
      return;
    }
    const acts = el("ol", { class: "skate-list" });
    box.replaceChildren(el("b", { text: `Strava${st.data.athlete ? " · " + st.data.athlete : ""}` }),
      el("p", { class: "meta", text: "Your recent activities with GPS (skates first). Tap one to log it." }), acts,
      el("button", { type: "button", class: "linkish", text: "Disconnect Strava", onclick: async () => {
        if (!confirm("Disconnect Strava from Wild Ice?")) return;
        await S.disconnect(); box.replaceChildren(el("b", { text: "Strava" }), el("p", { class: "meta", text: "Disconnected." }));
      } }));
    const r = await S.activities().catch(() => null);
    if (!r || r.status !== 200) { acts.replaceWith(el("p", { class: "warn", text: (r && r.data.error) || "Couldn't reach Strava, try again" })); return; }
    if (!r.data.activities.length) { acts.replaceWith(el("p", { class: "meta", text: "No activities with GPS in the last 60 days." })); return; }
    for (const a of r.data.activities.slice(0, 12)) {
      const li = el("li", { class: "acct-row" }, el("button", { type: "button", class: "acct-main", onclick: () => {
        list.prepend(trackCard({ name: a.name }, async () => {
          const p = await S.points(a.id);
          if (p.status !== 200) throw Object.assign(new Error("strava"), { userMessage: p.data.error || "Couldn't get this activity from Strava" });
          return p.data.points;
        }, opts, "strava"));
        list.scrollIntoView({ behavior: "smooth" });
      } }, el("b", { text: a.name }),
        el("span", { class: "meta", text: `${shortDate(a.start.slice(0, 10))} · ${a.type === "IceSkate" ? "Ice skate" : a.type} · ${a.minutes} min` })));
      acts.append(li);
    }
  })();
  return box;
}

// opts: {joined: bool, features, queue(report) -> void, onJoin(), resolveLink(url), sharedLink?,
//        strava?: {status(), activities(), points(id), disconnect(), authorize()}}
export function renderUpload(mount, opts) {
  if (!opts.joined) {
    mount.replaceChildren(el("h2", { text: "Upload a track" }),
      el("p", { class: "meta", text: "Upload a GPX or FIT file from your watch or Strava, and it becomes a trip report on the lake you skated. Join Wild Ice (free, just your name) to post reports." }),
      el("button", { type: "button", class: "act", text: "Join Wild Ice", onclick: opts.onJoin }));
    return;
  }
  const list = el("div", { class: "uploads" });
  const input = el("input", { type: "file", accept: ".gpx,.fit,.gz", multiple: true, class: "file-in", id: "track-file" });
  input.addEventListener("change", () => {
    const files = [...input.files];
    input.value = "";
    for (const f of files) list.prepend(fileCard(f, opts));
  });
  mount.replaceChildren(el("h2", { text: "Upload a track" }),
    linkBox(opts),
    opts.strava ? stravaBox(opts, list) : null,
    el("h3", { text: "Or pick a file" }),
    el("p", { class: "meta", text: "GPX, FIT or .fit.gz from your watch or an export. The track stays on your phone: only the lake, day, minutes on the ice and one point are sent." }),
    el("label", { class: "act file-label", for: "track-file", text: "Choose track files" }), input, list);
}

const KINDS = [["marsh", "Marsh"], ["river", "River"], ["slough", "Slough"], ["pond", "Pond"], ["other", "Other"]];

// A track off the catalog lakes: name the place and say what it is; resolves to a match.
function newSpotForm(card, file, sum, opts, resolve) {
  let kind = "marsh";
  const name = el("input", { type: "text", maxlength: "60", placeholder: "Name, e.g. Potter Marsh", "aria-label": "Spot name" });
  const msg = el("p", { class: "status" });
  const kinds = el("div", { class: "fchips" }, ...KINDS.map(([k, t]) => el("button", { type: "button",
    class: "fchip" + (k === kind ? " on" : ""), text: t, onclick: (e) => {
      kind = k; [...kinds.children].forEach((b) => b.classList.toggle("on", b === e.currentTarget)); } })));
  const add = el("button", { type: "button", class: "act on", text: "Add this spot", onclick: async () => {
    if (!name.value.trim()) { msg.textContent = "Give it a name"; name.focus(); return; }
    add.disabled = true; msg.textContent = "Adding…";
    const r = await opts.addSpot({ name: name.value.trim(), kind, lat: sum.point.lat, lon: sum.point.lon, bbox: sum.bbox });
    if (!r.ok) { msg.textContent = r.error; add.disabled = false; return; }
    resolve({ lakeId: r.id, name: r.name, minutes: sum.minutes, day: sum.day, point: sum.point, existing: r.existing });
  } });
  card.replaceChildren(el("b", { text: file.name }),
    el("p", { class: "meta", text: `${shortDate(sum.day)} ${sum.day.slice(0, 4)} · ${sum.minutes} min · not on a lake we track` }),
    el("p", { text: "Skated a marsh, river or slough? Add it as a spot. There's no satellite or ice model for these, so other skaters will rely on reports like yours." }),
    name, kinds, add, msg,
    el("button", { type: "button", class: "linkish", text: "Not ice skating? Skip this track", onclick: () => {
      card.replaceChildren(el("b", { text: file.name }), el("p", { class: "meta", text: "Skipped." })); resolve(null); } }));
}

function fileCard(file, opts) {
  return trackCard({ name: file.name }, () => readTrackFile(file), opts, null);
}

// One track (a file, or a Strava activity): find the lake(s) it's on, or offer a new spot,
// then post the trip report. getPoints() -> [{lat, lon, t}]; via: null or "strava".
function trackCard(file, getPoints, opts, via) {
  const card = el("section", { class: "upload-card" }, el("b", { text: file.name }), el("p", { class: "meta", text: "Reading…" }));
  (async () => {
    let matches, points;
    try {
      points = await getPoints();
      matches = matchLakes(points, opts.features);
    } catch (e) {
      card.replaceChildren(el("b", { text: file.name }),
        el("p", { class: "warn", text: e instanceof TrackError ? e.message : e && e.userMessage ? e.userMessage : "Couldn't read this track" }));
      return;
    }
    if (!matches.length) {
      const sum = trackSummary(points);
      if (!sum || !opts.addSpot) {
        card.replaceChildren(el("b", { text: file.name }),
          el("p", { class: "warn", text: "This track is under 10 minutes, so there's nothing to log." }));
        return;
      }
      // Not on a catalog lake: a marsh, river or slough. Add it as a new spot.
      const m = await new Promise((resolve) => newSpotForm(card, file, sum, opts, resolve));
      if (!m) return;
      matches = [m];
    }
    let pick = matches[0], rating = "skated", grade = null;
    const posted = [];
    let pickers = null;
    function makePickers() {
      pickers = matches.length > 1 ? el("div", { class: "row" }, ...matches.map((m) => el("button", {
        type: "button", class: "act", text: `${m.name || m.lakeId} · ${m.minutes} min`,
        onclick: () => { pick = m; redraw(); } }))) : null;
    }
    makePickers();
    const gradeSel = el("select", { "aria-label": "Ice grade", class: "grade-sel" },
      el("option", { value: "", text: "Grade (optional)" }), ...GRADES.map((g) => el("option", { value: g, text: g })));
    gradeSel.addEventListener("change", () => { grade = gradeSel.value || null; });
    const note = el("textarea", { maxlength: "1000", rows: "3", class: "story-in",
      placeholder: "Trip report (optional, everyone sees it): how was the ice, where did you get on…" });
    const msg = el("p", { class: "status" });
    const ratings = el("div", { class: "row" },
      ...[["skated", "Skateable"], ["rough", "Rough ice"]].map(([r, t]) => el("button", { type: "button",
        class: "act" + (r === rating ? " sel" : ""), text: t, onclick: () => { rating = r; redraw(); } })));
    const send = el("button", { type: "button", class: "act on", text: "Post trip report", onclick: () => {
      opts.queue(makeReport({ lakeId: pick.lakeId, rating, grade, story: note.value, day: pick.day,
        trackMinutes: pick.minutes, point: pick.point, storage: opts.storage, via }));
      posted.push(`${pick.name || pick.lakeId}, ${shortDate(pick.day)}, ${pick.minutes} min`);
      // A track over several lakes: offer the others next.
      matches = matches.filter((m) => m !== pick);
      if (matches.length) {
        pick = matches[0];
        note.value = "";
        makePickers();
        redraw();
        return;
      }
      card.replaceChildren(el("b", { text: file.name }),
        ...posted.map((t) => el("p", { class: "meta", text: `Posted: ${t}.` })));
    } });
    function redraw() {
      card.replaceChildren(...posted.map((t) => el("p", { class: "meta", text: `Posted: ${t}.` })),
        el("b", { text: `${pick.name || pick.lakeId}` }),
        el("p", { class: "meta", text: `${shortDate(pick.day)} ${pick.day.slice(0, 4)} · ${pick.minutes} min on the ice · ${file.name}` }),
        pickers, ratings, gradeSel, note, send, msg);
      if (pickers) [...pickers.children].forEach((b, i) => b.classList.toggle("sel", matches[i] === pick));
      [...ratings.children].forEach((b, i) => b.classList.toggle("sel", ["skated", "rough"][i] === rating));
    }
    redraw();
  })();
  return card;
}
