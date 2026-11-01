// Last-month weather chart for the lake panel: two small panels sharing one x axis.
//   1. Temperature (C): air low-high band, air mean, estimated water temperature.
//   2. Ice and snow (cm): estimated ice thickness, daily snowfall.
// Hover or tap shows every value for that day; a table holds the same numbers.

const NS = "http://www.w3.org/2000/svg";
const W = 340, H = 130, PAD = { l: 34, r: 8, t: 8, b: 20 };

function svg(tag, attrs = {}) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}

function niceStep(span) {
  const raw = span / 4;
  const p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw);
}

function scaleY(lo, hi) {
  const step = niceStep(Math.max(hi - lo, 1));
  const min = Math.floor(lo / step) * step, max = Math.ceil(hi / step) * step;
  const y = (v) => PAD.t + (H - PAD.t - PAD.b) * (1 - (v - min) / (max - min));
  const ticks = [];
  for (let v = min; v <= max + 1e-9; v += step) ticks.push(Math.round(v * 10) / 10);
  return { y, ticks };
}

function fmtDay(iso) {
  const d = new Date(iso + "T12:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function line(xs, ys, cls) {
  const d = xs.map((x, i) => (i ? "L" : "M") + x.toFixed(1) + "," + ys[i].toFixed(1)).join("");
  return svg("path", { d, class: cls });
}

// One panel: axes, gridlines, marks, crosshair. Returns the svg and a hover hook.
function panel(s, title, unit, lo, hi, draw, zeroLine) {
  const n = s.day.length;
  const x = (i) => PAD.l + (W - PAD.l - PAD.r) * (n === 1 ? 0.5 : i / (n - 1));
  const { y, ticks } = scaleY(lo, hi);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "wx-svg", role: "img", "aria-label": title });
  for (const t of ticks) {
    root.append(svg("line", { x1: PAD.l, x2: W - PAD.r, y1: y(t), y2: y(t), class: "wx-grid" }));
    const lab = svg("text", { x: PAD.l - 4, y: y(t) + 3, class: "wx-tick", "text-anchor": "end" });
    lab.textContent = t + (t === ticks[ticks.length - 1] ? " " + unit : "");
    root.append(lab);
  }
  if (zeroLine) root.append(svg("line", { x1: PAD.l, x2: W - PAD.r, y1: y(0), y2: y(0), class: "wx-zero" }));
  for (const i of [0, Math.floor((n - 1) / 2), n - 1]) {
    const lab = svg("text", { x: x(i), y: H - 5, class: "wx-tick", "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" });
    lab.textContent = fmtDay(s.day[i]);
    root.append(lab);
  }
  draw(root, x, y);
  const hair = svg("line", { y1: PAD.t, y2: H - PAD.b, class: "wx-hair", visibility: "hidden" });
  root.append(hair);
  return { root, x, hair };
}

const range = (a) => [Math.min(...a), Math.max(...a)];

export function renderWeatherChart(s, mount) {
  const n = s.day.length;
  if (!n) return;
  const idx = [...Array(n).keys()];

  const [tlo, thi] = range([...s.t_min, ...s.t_max, ...s.water_c, 0]);
  const temp = panel(s, "Air and estimated water temperature, last " + n + " days", "°C", tlo, thi, (g, x, y) => {
    const band = idx.map((i) => x(i).toFixed(1) + "," + y(s.t_max[i]).toFixed(1))
      .concat(idx.slice().reverse().map((i) => x(i).toFixed(1) + "," + y(s.t_min[i]).toFixed(1)));
    g.append(svg("polygon", { points: band.join(" "), class: "wx-band" }));
    g.append(line(idx.map(x), s.t_mean.map(y), "wx-air"));
    g.append(line(idx.map(x), s.water_c.map(y), "wx-water"));
  }, true);

  const [, ihi] = range([...s.ice_cm, ...s.snow_cm, 5]);
  const ice = panel(s, "Estimated ice thickness and daily snowfall, last " + n + " days", "cm", 0, ihi, (g, x, y) => {
    const bw = Math.max(2, (W - PAD.l - PAD.r) / n - 2);
    idx.forEach((i) => {
      if (s.snow_cm[i] <= 0) return;
      const top = y(s.snow_cm[i]), base = y(0);
      g.append(svg("rect", { x: x(i) - bw / 2, y: top, width: bw, height: Math.max(1, base - top), rx: 1.5, class: "wx-snow" }));
    });
    g.append(line(idx.map(x), s.ice_cm.map(y), "wx-ice"));
  }, false);

  const key = (cls, text) => {
    const k = document.createElement("span");
    k.className = "wx-key";
    const sw = document.createElement("i");
    sw.className = cls;
    k.append(sw, document.createTextNode(text));
    return k;
  };
  const legend1 = document.createElement("div");
  legend1.className = "wx-legend";
  legend1.append(key("k-air", "Air (mean)"), key("k-band", "Air low–high"), key("k-water", "Water (est.)"));
  const legend2 = document.createElement("div");
  legend2.className = "wx-legend";
  legend2.append(key("k-ice", "Ice (est.)"), key("k-snow", "Snowfall"));

  const tip = document.createElement("div");
  tip.className = "wx-tip";
  tip.hidden = true;

  const wrap = document.createElement("div");
  wrap.className = "wx";
  const h = document.createElement("p");
  h.className = "meta";
  h.textContent = "Last " + n + " days";
  wrap.append(h, legend1, temp.root, legend2, ice.root, tip);

  // Crosshair: snap to the nearest day on either panel; one readout for every series.
  const show = (evt, p) => {
    const box = p.root.getBoundingClientRect();
    const px = ((evt.clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(n - 1, Math.round(((px - PAD.l) / (W - PAD.l - PAD.r)) * (n - 1))));
    for (const q of [temp, ice]) {
      q.hair.setAttribute("x1", q.x(i)); q.hair.setAttribute("x2", q.x(i));
      q.hair.setAttribute("visibility", "visible");
    }
    tip.replaceChildren();
    const row = (label, value) => {
      const r = document.createElement("div");
      const b = document.createElement("b");
      b.textContent = value;
      r.append(b, document.createTextNode(" " + label));
      tip.append(r);
    };
    const head = document.createElement("div");
    head.className = "wx-tip-day";
    head.textContent = fmtDay(s.day[i]);
    tip.append(head);
    row("air mean", s.t_mean[i] + " °C");
    row("air low / high", s.t_min[i] + " / " + s.t_max[i] + " °C");
    row("water (est.)", s.water_c[i] + " °C");
    row("ice (est.)", s.ice_cm[i] + " cm");
    row("snowfall", s.snow_cm[i] + " cm");
    tip.hidden = false;
  };
  const hide = () => {
    tip.hidden = true;
    for (const q of [temp, ice]) q.hair.setAttribute("visibility", "hidden");
  };
  for (const p of [temp, ice]) {
    p.root.addEventListener("pointermove", (e) => show(e, p));
    p.root.addEventListener("pointerdown", (e) => show(e, p));
    p.root.addEventListener("pointerleave", hide);
  }

  // Same numbers as a table, for reading without hovering.
  const det = document.createElement("details");
  const sum = document.createElement("summary");
  sum.textContent = "Show numbers";
  const table = document.createElement("table");
  table.className = "wx-table";
  const cols = [["Day", null], ["Air low", "t_min"], ["Air high", "t_max"], ["Air mean", "t_mean"],
    ["Water", "water_c"], ["Ice cm", "ice_cm"], ["Snow cm", "snow_cm"]];
  const tr = document.createElement("tr");
  for (const [label] of cols) { const th = document.createElement("th"); th.textContent = label; tr.append(th); }
  table.append(tr);
  for (const i of idx.slice().reverse()) {
    const r = document.createElement("tr");
    for (const [, k] of cols) {
      const td = document.createElement("td");
      td.textContent = k ? s[k][i] : fmtDay(s.day[i]);
      r.append(td);
    }
    table.append(r);
  }
  det.append(sum, table);
  wrap.append(det);
  mount.replaceChildren(wrap);
}
