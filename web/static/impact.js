// Impact page: same engine and assumptions as the Power BI exports (GET /scenario, /scenarios).
import { lineChart, fmt, MONTHS } from "./charts.js";

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const C = { plan: "#2a78d6", queue: "#eb6834", sq: "#898781" };
const LEVERS = [
  { key: "transfers_removed", q: "transfers", pct: true, note: "OneCase intake: CaseTrack already runs at 0%" },
  { key: "info_only_first_contact", q: "info", pct: true, note: "Answered on the one screen at first contact" },
  { key: "estimated_read_reduction", q: "estimates", pct: true, note: "Billing uses the smart read (feedback loop)" },
  { key: "calderfield_agents_restored", q: "agents", pct: false, note: "Calderfield lost 35 agents (72 → 37)" },
];
let meta, statusQuo, current = null;

const money = v => v == null ? "n/a" : Math.abs(v) >= 1e6 ? `$${fmt(v / 1e6, 2)}M` : `$${fmt(v / 1e3, 0)}k`;
const monthLabel = m => `${MONTHS[+m.slice(5) - 1]} ${m.slice(2, 4)}`;

async function api(p) { const r = await fetch(p); if (!r.ok) throw new Error(await r.text()); return r.json(); }

function renderLevers() {
  $("#levers").innerHTML = LEVERS.map(l => {
    const spec = meta.levers[l.key];
    return `<div class="lever"><div class="top"><label for="${l.q}">${esc(spec.label.replace(/ \(.*\)/, ""))}</label>
      <output id="${l.q}-out"></output></div>
      <input type="range" id="${l.q}" min="${spec.min}" max="${spec.max}" step="${l.pct ? 0.05 : 1}" value="${spec.default}">
      <small>${esc(l.note)}</small></div>`; }).join("");
  LEVERS.forEach(l => $("#" + l.q).addEventListener("input", () => { markPreset(null); update(); }));
}

function renderPresets() {
  $("#presets").innerHTML = meta.scenarios.map(s =>
    `<button type="button" data-id="${s.id}" aria-pressed="false" title="${esc(s.note)}">${esc(s.name)}</button>`).join("");
  $("#presets").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    const s = meta.scenarios.find(x => x.id === b.dataset.id);
    LEVERS.forEach(l => { $("#" + l.q).value = s.levers[l.key]; });
    markPreset(s.id); update();
  });
}

function markPreset(id) { document.querySelectorAll("#presets button").forEach(b => b.setAttribute("aria-pressed", b.dataset.id === id)); }

let timer;
function update() {
  LEVERS.forEach(l => { const v = +$("#" + l.q).value; $(`#${l.q}-out`).textContent = l.pct ? `${Math.round(v * 100)}%` : fmt(v); });
  clearTimeout(timer);
  timer = setTimeout(async () => {
    const qs = LEVERS.map(l => `${l.q}=${$("#" + l.q).value}`).join("&");
    current = await api(`/scenario?${qs}`);
    render();
  }, 60);
}

function render() {
  const s = current.summary, m = current.months, target = meta.score_model.target;
  const planHit = s.static.first_month_target_met, queueHit = s.queue.first_month_target_met;
  const v = $("#verdict");
  if (planHit) { v.className = "verdict yes"; v.textContent = `4.0 reached in month ${planHit} on the plan method.`; }
  else if (queueHit) { v.className = "verdict yes"; v.textContent = `Plan method stops at ${fmt(s.static.score_month12, 2)}. 4.0 is reached in month ${queueHit} only if the backlog clears as history suggests.`; }
  else { v.className = "verdict no"; v.textContent = `4.0 is not reached. Best by month 12: ${fmt(s.static.score_month12, 2)} (plan method), ${fmt(s.queue.score_month12, 2)} (backlog-aware).`; }

  const sq = statusQuo.summary;
  const payback = s.costs_missing.length ? "Costs TBD"
    : s.payback_months ? `${s.payback_months} months` : s.has_costs ? "Not on handling savings alone" : "No cost";
  $("#tiles").innerHTML = [
    tile("Days to close, month 12", fmt(s.static.days_month12, 1), `Backlog-aware <b>${fmt(s.queue.days_month12, 1)}</b> · today 38.2 · 4.0 needs 19.0`),
    tile("Regulator score, month 12", fmt(s.static.score_month12, 2), `Backlog-aware <b>${fmt(s.queue.score_month12, 2)}</b> · target ${fmt(target, 1)}`),
    tile("Open backlog, month 12", fmt(s.backlog_month12), `Status quo <b>${fmt(sq.backlog_month12)}</b> · today ${fmt(meta.baseline.open_backlog)}`),
    tile("Handling saving a year", money(s.annual_saving_full_effect), `Year 1 with ramp <b>${money(s.annual_saving_y1)}</b>`),
    tile("Payback", payback, s.costs_missing.length ? `Set in assumptions.yaml: ${esc(s.costs_missing.join(", "))}` : "Handling savings only; value case adds penalty avoided"),
  ].join("");

  const labels = m.map(r => monthLabel(r.month));
  const series = [
    { name: "Plan method", color: C.plan, values: m.map(r => r.score_static) },
    { name: "Backlog-aware", color: C.queue, values: m.map(r => r.score_queue) },
    { name: "Status quo", color: C.sq, values: statusQuo.months.map(r => r.score_queue), width: 1.5 },
  ];
  $("#score-legend").innerHTML = legend(series);
  lineChart($("#score-chart"), { labels, series, min: 1, max: 5, ref: { value: target, label: `Target ${fmt(target, 1)}` },
    format: v => fmt(v, 2), height: 270 });
  const bl = [
    { name: "This scenario", color: C.plan, values: m.map(r => r.backlog) },
    { name: "Status quo", color: C.sq, values: statusQuo.months.map(r => r.backlog), width: 1.5 },
  ];
  $("#backlog-legend").innerHTML = legend(bl);
  lineChart($("#backlog-chart"), { labels, series: bl, min: 0, format: v => fmt(v, 0), height: 270 });
}

const tile = (label, value, sub) => `<div class="panel tile"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;
const legend = ss => ss.map(s => `<span><i class="line" style="background:${s.color}"></i>${esc(s.name)}</span>`).join("");

const all = await api("/scenarios");
meta = { scenarios: all.scenarios.map(s => ({ id: s.id, name: s.name, note: s.note, levers: s.levers })),
         levers: all.levers, baseline: all.baseline, score_model: all.score_model };
statusQuo = all.scenarios.find(s => s.id === "status_quo");
$("#foot").textContent = `Same engine and assumptions as data/exports/scenarios.csv and lever_grid.csv (and the Power BI project). ` +
  `Baseline ${all.baseline.month}: ${all.baseline.avg_days_to_close} days, score ${all.baseline.regulator_score} actual ` +
  `(model at 38.2 days: ${fmt(all.score_model.intercept + all.score_model.slope_per_day * all.baseline.avg_days_to_close, 2)}). ` +
  `Status quo line is backlog-aware: on the plan method it stays flat.`;
renderPresets(); renderLevers();
const rec = meta.scenarios.find(s => s.id === "recommended");
LEVERS.forEach(l => { $("#" + l.q).value = rec.levers[l.key]; }); markPreset("recommended");
update();
addEventListener("resize", () => current && render());
