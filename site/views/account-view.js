// Account page: name and photo, my reports, my phones, download and delete.
import { shortDate } from "../explore.js";
import { account, prepAvatar } from "../icelog.js";

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

const RATING = { skated: "Skateable", rough: "Rough ice", snow: "Snow on ice", water: "Open water" };

export function avatarUrl(base, id) {
  return id ? `${base}/api/avatars/${encodeURIComponent(id)}` : null;
}

// A round picture, or the first letter of the name when there's no photo.
export function avatarEl(url, name, size = 40) {
  const box = el("span", { class: "avatar", style: `width:${size}px;height:${size}px;font-size:${Math.round(size * 0.45)}px` });
  if (url) box.append(el("img", { src: url, alt: "", loading: "lazy" }));
  else box.textContent = (name || "?").trim().charAt(0).toUpperCase() || "?";
  return box;
}

// opts: {ICELOG, lakeName(id), onChanged(), onSignedOut(), openLake(id), joinSection: Node}
export async function renderAccount(page, opts) {
  const o = opts.ICELOG;
  const meRes = await account.me(o);
  if (meRes.status !== 200) {
    page.replaceChildren(el("p", { class: "meta", text: "You haven't joined yet." }),
      opts.joinSection);
    return;
  }
  const me = meRes.data;
  const msg = el("p", { class: "status acct-msg" });
  const say = (t) => { msg.textContent = t; };

  // --- name and photo ---
  const pic = el("span", { class: "acct-pic" }, avatarEl(avatarUrl(o.base, me.avatar), me.name, 88));
  const file = el("input", { type: "file", accept: "image/*", class: "file-in", id: "avatar-file" });
  file.addEventListener("change", async () => {
    const f = file.files[0];
    file.value = "";
    if (!f) return;
    say("Uploading…");
    const r = await account.photo(await prepAvatar(f), o);
    if (r.status !== 200) { say(r.data.error || "Couldn't upload, try again"); return; }
    pic.replaceChildren(avatarEl(avatarUrl(o.base, r.data.avatar), me.name, 88));
    say("Photo updated");
    opts.onChanged();
  });
  const name = el("input", { type: "text", value: me.name, maxlength: "40", "aria-label": "Display name" });
  const profile = el("section", { class: "acct" },
    el("div", { class: "acct-head" }, pic,
      el("div", {}, el("label", { class: "act small file-label", for: "avatar-file", text: me.avatar ? "Change photo" : "Add a photo" }), file)),
    el("label", { text: "Display name" }),
    el("div", { class: "report-note" }, name, el("button", { type: "button", class: "act small", text: "Save", onclick: async () => {
      const r = await account.rename(name.value, o);
      say(r.status === 200 ? "Name saved" : r.data.error || "Couldn't save, try again");
      if (r.status === 200) opts.onChanged();
    } })));

  // --- my reports ---
  const reportList = el("ol", { class: "skate-list" });
  const reportsBox = el("section", { class: "acct" }, el("h3", { text: "My reports" }), reportList);
  account.reports(o).then((r) => {
    const rows = r.status === 200 ? r.data.reports : [];
    if (!rows.length) { reportList.replaceWith(el("p", { class: "meta", text: "None yet." })); return; }
    for (const rep of rows) {
      const li = el("li", { class: "acct-row" },
        el("button", { type: "button", class: "acct-main", onclick: () => opts.openLake(rep.lake_id) },
          el("b", { text: opts.lakeName(rep.lake_id) }),
          el("span", { class: "meta", text: [shortDate(rep.day) + " " + rep.day.slice(0, 4), RATING[rep.rating] || rep.rating,
            rep.grade, rep.track_minutes ? `${rep.track_minutes} min track` : null, rep.has_photo ? "photo" : null].filter(Boolean).join(" · ") })),
        el("button", { type: "button", class: "act small danger", text: "Delete", onclick: async () => {
          if (!confirm("Delete this report (and its photo)?")) return;
          const d = await account.deleteReport(rep.id, o);
          if (d.status === 200) li.remove(); else say(d.data.error || "Couldn't delete, try again");
        } }));
      reportList.append(li);
    }
  });

  // --- phones ---
  const phoneList = el("ol", { class: "skate-list" });
  const phones = el("section", { class: "acct" }, el("h3", { text: "Signed in on" }), phoneList);
  account.devices(o).then((r) => {
    for (const d of (r.status === 200 ? r.data.devices : [])) {
      const li = el("li", { class: "acct-row" },
        el("span", { class: "acct-main" }, el("b", { text: d.label + (d.current ? " (this phone)" : "") }),
          el("span", { class: "meta", text: `last used ${shortDate(d.last_seen.slice(0, 10))}` })),
        el("button", { type: "button", class: "act small", text: "Sign out", onclick: async () => {
          if (!confirm(d.current ? "Sign this phone out? You'll need a new link to sign back in." : "Sign that phone out?")) return;
          const s = await account.signOut(d, o);
          if (s.status !== 200) { say(s.data.error || "Couldn't sign out, try again"); return; }
          if (d.current) opts.onSignedOut(); else li.remove();
        } }));
      phoneList.append(li);
    }
  });

  // --- download and delete ---
  const data = el("section", { class: "acct" }, el("h3", { text: "Your data" }),
    el("button", { type: "button", class: "act", text: "Download my data", onclick: async () => {
      const r = await account.download(o);
      if (r.status !== 200) { say("Couldn't download, try again"); return; }
      const a = el("a", { href: URL.createObjectURL(new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" })),
        download: "wild-ice-my-data.json" });
      document.body.append(a); a.click(); a.remove();
    } }),
    me.role === "owner"
      ? el("p", { class: "meta", text: "Owner account." })
      : el("button", { type: "button", class: "act danger", text: "Delete my account", onclick: async () => {
        if (!confirm("Delete your account? Your name and photo are erased and your phones are signed out. Your reports stay as anonymous ice data; your comments show as \"Former skater\".")) return;
        const r = await account.remove(o);
        if (r.ok) opts.onSignedOut(); else say(r.error || "Couldn't delete, try again");
      } }));

  const owner = me.role === "owner"
    ? el("section", { class: "acct" }, el("a", { class: "act join-btn", href: "#review", text: "Review and numbers" })) : null;
  page.replaceChildren(...[profile, msg, owner, reportsBox, phones, data].filter(Boolean));
}
