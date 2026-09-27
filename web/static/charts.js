// Tiny SVG chart helpers. No libraries, works offline.
// Mark specs: bars <= 24px with 4px rounded data-end, 2px lines, >= 8px dots with a 2px surface ring,
// hairline solid grid, text in ink tokens (never the series colour), hover tooltip on every chart.
const NS = "http://www.w3.org/2000/svg";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}

function niceMax(v, steps = 4) {
  const raw = v / steps, mag = 10 ** Math.floor(Math.log10(raw)), n = raw / mag;
  const step = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
  return { max: step * steps, step };
}

const tip = (() => {
  let t;
  return {
    show(html, x, y) {
      if (!t) { t = document.createElement("div"); t.className = "tip"; t.setAttribute("role", "status"); document.body.appendChild(t); }
      t.innerHTML = html; t.style.display = "block";
      const w = t.offsetWidth, h = t.offsetHeight;
      t.style.left = Math.min(x + 14, innerWidth - w - 8) + "px";
      t.style.top = Math.max(8, y - h - 12) + "px";
    },
    hide() { if (t) t.style.display = "none"; },
  };
})();

// path for a column with 4px rounded top, square at the baseline
function colPath(x, y, w, h, r = 4) {
  if (h <= 0) return "";
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

const periodLabel = p => `${MONTHS[+p.slice(5) - 1]} ${p.slice(0, 4)}`;
const fmt = (n, d = 0) => n == null ? "n/a" : Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

// ------------------------------------------------------------------ bills vs reads (account panel)
export function billChart(host, months) {
  host.innerHTML = "";
  const W = Math.max(300, host.clientWidth), H = 210, m = { t: 14, r: 8, b: 26, l: 40 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
    "aria-label": "Billed kWh by month compared with meter reads" }, host);
  const defs = el("defs", {}, svg);
  const pat = el("pattern", { id: "hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
  el("rect", { width: 6, height: 6, fill: "var(--series-est)" }, pat);
  el("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "#b8481c", "stroke-width": 2 }, pat);

  const vals = months.flatMap(d => [d.billed_kwh, d.effective_kwh, d.read_kwh || 0]);
  const { max, step } = niceMax(Math.max(...vals) * 1.05);
  const iw = W - m.l - m.r, ih = H - m.t - m.b, band = iw / months.length;
  const y = v => m.t + ih - (v / max) * ih;
  const bw = Math.min(24, band * 0.62);

  for (let v = 0; v <= max + 1e-9; v += step) {
    el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: v === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }, svg);
    const t = el("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--muted)" }, svg);
    t.textContent = fmt(v);
  }

  months.forEach((d, i) => {
    const cx = m.l + band * i + band / 2, x = cx - bw / 2;
    if (d.corrected && d.billed_kwh !== d.effective_kwh) {
      // what was originally billed, as a pale wash behind the corrected bar
      el("path", { d: colPath(x, y(d.billed_kwh), bw, y(0) - y(d.billed_kwh)), fill: "var(--series-est)", opacity: 0.18 }, svg);
    }
    const est = d.read_type_used === "estimated" && !d.corrected;
    el("path", { d: colPath(x, y(d.effective_kwh), bw, y(0) - y(d.effective_kwh)),
      fill: est ? "url(#hatch)" : "var(--series-actual)" }, svg);
    const lab = el("text", { x: cx, y: H - 8, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)" }, svg);
    lab.textContent = MONTHS[+d.period.slice(5) - 1][0];
  });

  // meter reads: 2px line, gaps where no read was taken
  let dPath = "", pen = false;
  months.forEach((d, i) => {
    const cx = m.l + band * i + band / 2;
    if (d.read_kwh == null) { pen = false; return; }
    dPath += `${pen ? "L" : "M"}${cx},${y(d.read_kwh)}`; pen = true;
  });
  el("path", { d: dPath, fill: "none", stroke: "var(--ink)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
  months.forEach((d, i) => {
    if (d.read_kwh == null) return;
    el("circle", { cx: m.l + band * i + band / 2, cy: y(d.read_kwh), r: 4, fill: "var(--ink)", stroke: "#fff", "stroke-width": 2 }, svg);
  });

  // hover targets: the whole column band
  months.forEach((d, i) => {
    const hit = el("rect", { x: m.l + band * i, y: m.t, width: band, height: ih, fill: "transparent" }, svg);
    const html = `<b>${periodLabel(d.period)}</b><br>Billed ${fmt(d.effective_kwh)} kWh ` +
      `(${d.corrected ? "corrected" : d.read_type_used === "estimated" ? "estimate" : "actual read"})` +
      (d.corrected && d.billed_kwh !== d.effective_kwh ? `<br>Originally ${fmt(d.billed_kwh)} kWh` : "") +
      `<br>${d.read_kwh == null ? "No read taken" : `${d.read_type === "smart" ? "Smart" : "Manual"} read ${fmt(d.read_kwh)} kWh`}` +
      `<br>Amount $${fmt(d.effective_amount, 2)}`;
    hit.addEventListener("mousemove", e => tip.show(html, e.clientX, e.clientY));
    hit.addEventListener("mouseleave", tip.hide);
  });
}

// ------------------------------------------------------------------ multi-line chart (impact page)
// series: [{name, color, values:[..], width?}], x labels, opts: {min, max, ref:{value,label}, fmt, unit}
export function lineChart(host, { labels, series, min = 0, max, ref, format = v => fmt(v, 1), unit = "", height = 260 }) {
  host.innerHTML = "";
  const W = Math.max(320, host.clientWidth), H = height, m = { t: 16, r: 118, b: 28, l: 48 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img" }, host);
  const all = series.flatMap(s => s.values).concat(ref ? [ref.value] : []);
  const top = max ?? niceMax(Math.max(...all) * 1.08).max;
  const { step } = niceMax(top - min);
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const x = i => m.l + (iw * i) / (labels.length - 1);
  const y = v => m.t + ih - ((Math.min(Math.max(v, min), top) - min) / (top - min)) * ih;

  for (let v = min; v <= top + 1e-9; v += step) {
    el("line", { x1: m.l, x2: m.l + iw, y1: y(v), y2: y(v), stroke: v === min ? "var(--axis)" : "var(--grid)" }, svg);
    const t = el("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--muted)" }, svg);
    t.textContent = format(v).replace(/\.0$/, "");
  }
  if (unit) { const u = el("text", { x: m.l - 8, y: m.t - 5, "text-anchor": "end", "font-size": 10, fill: "var(--muted)" }, svg); u.textContent = unit; }
  labels.forEach((l, i) => {
    if (i % 2 && labels.length > 8) return;
    const t = el("text", { x: x(i), y: H - 8, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)" }, svg);
    t.textContent = l;
  });
  if (ref) {
    el("line", { x1: m.l, x2: m.l + iw, y1: y(ref.value), y2: y(ref.value), stroke: "var(--pass)", "stroke-width": 1.5 }, svg);
    const t = el("text", { x: m.l + iw + 6, y: y(ref.value) + 4, "font-size": 12, "font-weight": 700, fill: "var(--pass)" }, svg);
    t.textContent = ref.label;
  }
  // direct end labels; nudge apart only if they would overlap (with leader line)
  const ends = series.map(s => ({ s, yv: y(s.values[s.values.length - 1]) })).sort((a, b) => a.yv - b.yv);
  for (let i = 1; i < ends.length; i++) if (ends[i].yv - ends[i - 1].yv < 15) ends[i].ly = (ends[i - 1].ly ?? ends[i - 1].yv) + 15;
  series.forEach(s => {
    const d = s.values.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join("");
    el("path", { d, fill: "none", stroke: s.color, "stroke-width": s.width || 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    const last = s.values.length - 1;
    el("circle", { cx: x(last), cy: y(s.values[last]), r: 4, fill: s.color, stroke: "#fff", "stroke-width": 2 }, svg);
  });
  ends.forEach(({ s, yv, ly }) => {
    const ty = ly ?? yv;
    if (ly != null) el("line", { x1: x(labels.length - 1) + 5, y1: yv, x2: m.l + iw + 8, y2: ty - 4, stroke: "var(--axis)" }, svg);
    const t = el("text", { x: m.l + iw + 10, y: ty + 4, "font-size": 12, fill: "var(--ink-2)" }, svg);
    t.textContent = `${s.name} ${format(s.values[s.values.length - 1])}`;
  });
  // crosshair + tooltip
  const cross = el("line", { y1: m.t, y2: m.t + ih, stroke: "var(--axis)", visibility: "hidden" }, svg);
  const hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" }, svg);
  hit.addEventListener("mousemove", e => {
    const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * (W / r.width);
    const i = Math.max(0, Math.min(labels.length - 1, Math.round(((px - m.l) / iw) * (labels.length - 1))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    tip.show(`<b>${labels[i]}</b><br>` + series.map(s => `${s.name}: ${format(s.values[i])}`).join("<br>"), e.clientX, e.clientY);
  });
  hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); tip.hide(); });
}

export { fmt, periodLabel, MONTHS };
