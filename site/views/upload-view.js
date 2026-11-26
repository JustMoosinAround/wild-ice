// Upload tab: GPX / FIT (.gz) tracks become trip reports. Each file is read on the
// phone, matched to catalog lakes, and sent as lake + day + minutes + one point.
import { shortDate } from "../explore.js";
import { GRADES, makeReport } from "../icelog.js";
import { TrackError, matchLakes, readTrackFile } from "../track.js";

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

// opts: {joined: bool, features, queue(report) -> void, onJoin()}
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
    el("p", { class: "meta", text: "GPX, FIT or .fit.gz from your watch or a Strava export. The track stays on your phone: only the lake, day, minutes on the ice and one point are sent." }),
    el("label", { class: "act file-label", for: "track-file", text: "Choose track files" }), input, list);
}

function fileCard(file, opts) {
  const card = el("section", { class: "upload-card" }, el("b", { text: file.name }), el("p", { class: "meta", text: "Reading…" }));
  (async () => {
    let matches;
    try {
      matches = matchLakes(await readTrackFile(file), opts.features);
    } catch (e) {
      card.replaceChildren(el("b", { text: file.name }),
        el("p", { class: "warn", text: e instanceof TrackError ? e.message : "Couldn't read this file" }));
      return;
    }
    if (!matches.length) {
      card.replaceChildren(el("b", { text: file.name }),
        el("p", { class: "warn", text: "No catalog lake on this track (at least 10 minutes on one lake)." }));
      return;
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
        trackMinutes: pick.minutes, point: pick.point, storage: opts.storage }));
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
