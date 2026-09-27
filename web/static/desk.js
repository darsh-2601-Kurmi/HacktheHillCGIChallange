// Agent desk: intake (left), the one case (centre), the account (right), before/after toggle (top).
import { billChart, fmt, periodLabel } from "./charts.js";

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { meta: null, account: null, case: null, mode: "onecase", seen: new Set() };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `${r.status} ${r.statusText}`);
  return j;
}

const CHANNEL_LABEL = { "Web form": "Web", "Regulator referral": "Regulator" };
const TYPE_LABEL = { intake: "Intake", history: "History", bill_check: "Bill check", routing: "Routing", action: "Action",
  reassign: "Reassigned", resolved: "Resolved", note: "Note" };
const dt = s => new Date(s.replace(" ", "T"));
const hhmm = s => dt(s).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const day = d => d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

// ------------------------------------------------------------------ intake
function renderIntake() {
  const m = state.meta;
  $("#demo-tiles").innerHTML = m.demo.map(d =>
    `<button type="button" data-label="${d.label}" aria-pressed="false" aria-label="Demo customer ${d.label}" title="${esc(d.story)}">${d.label}</button>`).join("");
  $("#channels").innerHTML = m.channels.map((c, i) =>
    `<label><input type="radio" name="channel" value="${esc(c)}" ${i === 0 ? "checked" : ""}><span>${esc(CHANNEL_LABEL[c] || c)}</span></label>`).join("");
  $("#priorities").innerHTML = m.priorities.map(p =>
    `<label><input type="radio" name="priority" value="${p}" ${p === "P3" ? "checked" : ""}><span>${p}</span></label>`).join("");
  $("#category").innerHTML = m.categories.map(c => `<option>${esc(c)}</option>`).join("");
  $("#account-list").innerHTML = m.demo.map(d => `<option value="${d.account_id}">Demo ${d.label} · ${d.region}</option>`).join("");

  $("#demo-tiles").addEventListener("click", e => {
    const b = e.target.closest("button[data-label]"); if (!b) return;
    const d = m.demo.find(x => x.label === b.dataset.label);
    document.querySelectorAll("#demo-tiles button").forEach(x => x.setAttribute("aria-pressed", x === b));
    $("#story").textContent = `${d.label}: ${d.story}`;
    $("#account").value = d.account_id;
    document.querySelector(`input[name=channel][value="${d.intake.channel}"]`).checked = true;
    document.querySelector(`input[name=priority][value="${d.intake.priority}"]`).checked = true;
    $("#category").value = d.intake.category;
    $("#text").value = d.intake.free_text;
    loadAccount(d.account_id);
  });
  $("#account").addEventListener("change", () => $("#account").value && loadAccount($("#account").value));
  $("#account").addEventListener("input", debounce(async () => {
    const q = $("#account").value.trim(); if (q.length < 4) return;
    const rows = await api(`/accounts?q=${encodeURIComponent(q)}&limit=8`).catch(() => []);
    $("#account-list").innerHTML = rows.map(r => `<option value="${r.account_id}">${r.region} · ${r.meter_type}${r.demo_label ? " · demo " + r.demo_label : ""}</option>`).join("");
  }, 200));
  $("#intake").addEventListener("submit", createCase);
}

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

async function createCase(e) {
  e.preventDefault();
  $("#intake-err").textContent = "";
  const btn = $("#create"); btn.disabled = true;
  try {
    const c = await api("/intake", { method: "POST", body: {
      channel: document.querySelector("input[name=channel]:checked").value,
      account_id: $("#account").value.trim(), category: $("#category").value,
      priority: document.querySelector("input[name=priority]:checked").value, free_text: $("#text").value } });
    state.case = c; state.seen = new Set(); setMode("onecase");
    renderCase(); loadAccount(c.account_id);
  } catch (err) {
    $("#intake-err").textContent = err.message.includes("not found")
      ? `No account ${$("#account").value.trim()}. Check the number or pick a demo customer.` : err.message;
  } finally { btn.disabled = false; }
}

// ------------------------------------------------------------------ the case
function renderCase() {
  const c = state.case, host = $("#case");
  if (!c) { host.innerHTML = `<div class="empty"><h2>No case open</h2>Pick a demo customer or type an account, then create the case.</div>`; return; }
  const created = dt(c.created_at), due = dt(c.due_at);
  const resolved = c.status === "Resolved";
  const elapsed = resolved ? 0 : Math.min(1, (Date.now() - created) / (due - created));
  const r = c.routing || {};
  host.innerHTML = `
    <div class="case-head">
      <span class="case-id">${esc(c.case_id)}</span>
      <span class="status ${resolved ? "pass" : "info"}">${esc(c.status)}</span>
      <span class="spacer"></span>
    </div>
    <div class="team">${esc(c.owning_team)}</div>
    <p class="route-line">Routed once by rule <b>${esc(c.routing_rule)}</b>: ${esc(r.reason || "")}
      · ${esc(c.channel)} · ${esc(c.category)} · ${esc(c.priority)}</p>
    <div class="sla">
      <span>${c.sla_days}-day SLA · due ${day(due)}</span>
      <div class="meter" title="SLA used"><i style="width:${Math.max(2, elapsed * 100)}%"></i></div>
    </div>
    ${resolved ? "" : moreActions(c)}
    ${latest(c)}
    ${resolved ? resolvedBanner(c) : ""}
    ${c.bill_check ? checkCard(c) : ""}
    <p class="eyebrow" style="margin-top:16px">Case timeline</p>
    <ol class="wire">${c.timeline.map(ev => {
      const fresh = !state.seen.has(ev.id); state.seen.add(ev.id);
      return `<li class="${ev.type} ${fresh ? "fresh" : ""}"><div class="t"><b>${TYPE_LABEL[ev.type] || ev.type}</b>${hhmm(ev.ts)} · ${esc(ev.actor)}</div>
        <div class="s">${esc(ev.summary)}</div></li>`; }).join("")}</ol>
    <p class="wire-cap">One line, one case ID, from first contact to close. Nothing is re-keyed.</p>`;
  host.querySelectorAll("[data-act]").forEach(b => b.addEventListener("click", () => act(b.dataset.act)));
  const re = host.querySelector("#reassign-go");
  if (re) re.addEventListener("click", () => act("reassign", { team: host.querySelector("#reassign-team").value }));
  $(".seg [data-mode=legacy]").disabled = false;
  $(".seg [data-mode=legacy]").title = "";
}

// the result of the last click, kept near the top so it is visible on a projector without scrolling
function latest(c) {
  const ev = [...c.timeline.slice(1)].reverse().find(e => ["action", "reassign", "note", "intake"].includes(e.type));
  return ev && c.status !== "Resolved" ? `<p class="latest"><b>${TYPE_LABEL[ev.type]}:</b> ${esc(ev.summary)}</p>` : "";
}

function resolvedBanner(c) {
  const mins = c.minutes_to_resolve ?? 0;
  return `<div class="resolved-banner">✔ Resolved at first contact
    <small>${esc(c.resolution)} · ${mins < 1 ? "under a minute" : fmt(mins, 1) + " min"} · no transfer · ${c.sla_days} days inside SLA</small></div>`;
}

function checkCard(c) {
  const k = c.bill_check, resolved = c.status === "Resolved";
  const first = c.timeline.find(e => e.type === "bill_check")?.detail || k;   // what the agent acted on
  const shown = resolved ? first : k;
  const amt = shown.difference_dollars;
  const action = shown.action;
  const done = new Set(c.timeline.filter(e => e.type === "action").map(e => e.detail?.action));
  const canAct = !resolved && action && !done.has(action.code);
  const rules = `<p class="rules">Rules run (not AI): ${shown.rules.filter(r => r.rule <= 4).map(r =>
    r.status === "flag" || r.status === "info" ? `<b>${r.rule} ${esc(r.name.toLowerCase())}: ${r.status}</b>` : `${r.rule} ${r.status}`).join(" · ")}</p>`;
  if (resolved) {   // collapse: what was found, and the re-check
    return `<div class="check pass done"><div class="check-top">
      <span class="status pass">Fixed</span><h3>${esc(first.headline)}</h3>
      ${first.difference_dollars != null ? `<div class="amount">$${fmt(Math.abs(first.difference_dollars), 2)}<small>${first.difference_dollars > 0 ? "credited" : "re-billed"}</small></div>` : ""}
      </div><p class="alt" style="margin:6px 0 0">Re-check after the action: <b>${esc(k.headline)}</b>. ${esc(k.breakdown)}</p></div>`;
  }
  return `<div class="check ${shown.status}">
    <div class="check-top">
      <span class="status ${shown.status}">${shown.status === "flag" ? "Flag" : shown.status === "pass" ? "Pass" : "Info"}</span>
      <h3>${esc(shown.headline)}</h3>
      ${amt != null ? `<div class="amount">$${fmt(Math.abs(amt), 2)}<small>${amt > 0 ? "over-billed" : "under-billed"}</small></div>` : ""}
    </div>
    <div class="readout"><p class="eyebrow">Read to the customer</p>${esc(shown.explanation)}</div>
    ${canAct ? `<div class="act-row"><button class="btn" data-act="${action.code}">${esc(action.label)}${action.unit_cost ? ` · $${fmt(action.unit_cost, action.unit_cost % 1 ? 2 : 0)}` : ""}</button>
      <span class="alt">${esc(action.alternative || "")}${shown.solvable_remotely === false ? " · <b>Not solvable remotely</b>" : ""}</span></div>` : ""}
    ${rules}
  </div>`;
}

function moreActions(c) {
  const teams = state.meta.teams.filter(t => t !== c.owning_team);
  return `<div class="more">
    <select class="input" id="reassign-team" aria-label="Reassign to team">${teams.map(t => `<option>${esc(t)}</option>`).join("")}</select>
    <button class="btn secondary" id="reassign-go">Reassign, keep this case</button>
    <button class="btn quiet" data-act="explain">Resolve with explanation</button>
  </div>`;
}

async function act(action, extra = {}) {
  try {
    state.case = await api(`/cases/${state.case.case_id}/actions`, { method: "POST", body: { action, ...extra } });
    renderCase();
    if (state.mode === "legacy") renderLegacy();
    loadAccount(state.case.account_id);
  } catch (err) { alert(err.message); }
}

// ------------------------------------------------------------------ legacy path (before)
async function renderLegacy() {
  const c = state.case; if (!c) return;
  const L = await api(`/legacy-path/${c.case_id}`);
  disposeStage();
  const s = L.stats, T = s.if_transferred, N = s.if_not_transferred;
  const hops = L.hops.map((h, i) => {
    const link = i === 0 ? "" : {
      rekey: `<div class="link cut"><b>✂</b><span>history<br>lost</span></div>`,
      batch: `<div class="link batch"><b>☾</b><span>next day<br>batch</span></div>`,
      live: `<div class="link ok"></div>` }[h.handoff];
    return `${link}<div class="hop"><div class="sid">${h.system_id} · ${h.year_installed}</div><h4>${esc(h.system_name)}</h4>
      <div class="meta">${esc(h.integration)}${h.waits_for_batch ? " · waits overnight" : ""}</div>
      <div class="what">${esc(h.what_happens)}</div><div class="note">“${esc(h.system_note)}”</div></div>`;
  }).join("");
  const pct = v => `${Math.round(v * 100)}%`;
  const oc = L.onecase;
  $("#case").innerHTML = `
    <div class="legacy-title"><span class="sim">SIMULATED</span><h2>Same complaint, today's path</h2></div>
    <p class="route-line">${esc(c.channel)} contact for <span class="mono">${esc(c.account_id)}</span> ·
      ${esc(c.category)} · handled by ${esc(c.owning_team)}</p>
    <div class="stage" id="stage" hidden></div>
    <div class="hops" id="flat-hops">${hops}</div>
    <div class="compare" role="table" aria-label="Legacy path compared with OneCase">
      <div class="h" role="columnheader"></div><div class="h old" role="columnheader">Legacy path</div><div class="h new" role="columnheader">OneCase</div>
      <div>Systems the case crosses</div><div class="old big">${L.systems_touched}</div><div class="new big">1</div>
      <div>Screens the agent runs</div><div class="old big">${L.screens_for_agent}</div><div class="new big">1</div>
      <div>Chance of a transfer</div><div class="old big">${pct(s.transfer_probability)}</div><div class="new big">0%</div>
      <div>Days to close if transferred</div><div class="old big">${fmt(T.days, 1)}</div>
        <div class="new big">${oc.status === "Resolved" ? (oc.minutes_to_resolve < 1 ? "&lt; 1 min" : fmt(oc.minutes_to_resolve, 1) + " min") : "open · routed once"}</div>
      <div>Missed SLA if transferred</div><div class="old big">${pct(T.breach)}</div><div class="new">${oc.status === "Resolved" ? "Inside SLA" : "SLA clock running"}</div>
      <div>Reopened if transferred</div><div class="old big">${pct(T.reopen)}</div><div class="new">History kept on one case</div>
      <div>Handling cost</div><div class="old big">$${fmt(T.cost)}</div><div class="new">No transfer: $${fmt(N.cost)} or less</div>
    </div>
    <p class="stat-note">Odds and outcomes: ${fmt(s.complaints_logged)} complaints logged in ${esc(L.intake_system)}, data pack.
      Not transferred: ${fmt(N.days, 1)} days, ${pct(N.breach)} missed SLA, ${pct(N.reopen)} reopened. System notes: northwind_systems.csv.
      Today's average is ${fmt(L.today_avg_days, 1)} days (Sep 2026).</p>`;
  mountStage(L, c);
}

// Optional 3D stage over the flat hop boxes. Loaded on demand; any failure (no WebGL, phone, narrow
// screen, three.js missing, context lost) leaves the flat view exactly as it was.
let stage = null;
function disposeStage() { stage?.dispose(); stage = null; }
async function mountStage(L, c) {
  const host = $("#stage"), flat = $("#flat-hops");
  const fallBack = why => { console.warn("OneCase 3D stage off: " + (why?.stack || why)); disposeStage(); host.hidden = true; flat.hidden = false; };
  try {
    const gfx = await import("./gfx.js");
    if (!gfx.canUse3D()) return;
    const { mountLegacyStage } = await import("./legacy3d.js");
    if (!host.isConnected || state.mode !== "legacy") return;   // toggled away while loading
    host.hidden = false; flat.hidden = true;
    stage = await mountLegacyStage(host, L, c, { onFail: fallBack });
  } catch (e) { fallBack(e); }
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".seg button").forEach(b => b.setAttribute("aria-pressed", b.dataset.mode === mode));
  $(".desk").classList.toggle("legacy", mode === "legacy");
  if (mode !== "legacy") disposeStage();
  if (mode === "legacy") renderLegacy().catch(e => alert(e.message)); else renderCase();
}

// ------------------------------------------------------------------ account panel
async function loadAccount(id) {
  const host = $("#account-panel");
  let a;
  try { a = await api(`/accounts/${encodeURIComponent(id.trim())}`); }
  catch (e) { host.innerHTML = `<p class="eyebrow">Account</p><div class="empty" style="padding:24px 0">No account ${esc(id)}.</div>`; return; }
  state.account = a;
  const acc = a.account, est = a.months.filter(m => m.read_type_used === "estimated" && !m.corrected).length;
  host.innerHTML = `
    <p class="eyebrow">Account${acc.display_name ? " · " + esc(acc.display_name) : ""}</p>
    <div class="acc-head"><span class="acc-id">${esc(acc.account_id)}</span></div>
    <div class="badges">
      <span class="badge ${acc.meter_type}">${acc.meter_type === "smart" ? "Smart meter" : "Manual meter"}</span>
      <span class="badge region">${esc(acc.region)}</span>
      ${a.outage ? `<span class="badge outage">Outage · ${esc(a.outage.reference)}</span>` : ""}
    </div>
    <div class="section" style="margin-top:10px">
      <p class="eyebrow" style="margin-bottom:0">Billed vs read (kWh), last 12 months</p>
      <div class="legend"><span><i style="background:var(--series-actual)"></i>Billed on a read</span>
        <span><i style="background:repeating-linear-gradient(45deg,var(--series-est) 0 3px,#b8481c 3px 5px)"></i>Billed on an estimate${est ? ` (${est})` : ""}</span>
        <span><i class="line" style="background:var(--ink)"></i>${acc.meter_type === "smart" ? "Smart" : "Meter"} read</span></div>
      <div id="bill-chart"></div>
      <details class="table"><summary>Show as table</summary>
        <table class="data"><thead><tr><th>Month</th><th>Billed kWh</th><th>Basis</th><th>Read kWh</th><th>Amount</th></tr></thead>
        <tbody>${a.months.map(m => `<tr><td>${periodLabel(m.period)}</td><td>${fmt(m.effective_kwh)}</td>
          <td>${m.corrected ? "corrected" : m.read_type_used}</td><td>${m.read_kwh == null ? "no read" : fmt(m.read_kwh)}</td>
          <td>$${fmt(m.effective_amount, 2)}</td></tr>`).join("")}</tbody></table></details>
    </div>
    <div class="section">
      <p class="eyebrow">Past complaints (data pack) · ${a.past_complaints.length}</p>
      ${a.past_complaints.length ? `<ul class="past">${a.past_complaints.map(p => `<li>
        <div class="row1"><span><span class="mono">${esc(p.complaint_id)}</span> · ${esc(p.date_opened)}</span>
          <span class="days">${p.days_to_close == null ? "open" : p.days_to_close + " days"}</span></div>
        <div>${esc(p.category)} · ${esc(p.channel)} → ${esc(p.source_system)}</div>
        <div class="tags">${p.transferred ? `<span class="tag bad">Transferred</span>` : `<span class="tag">Not transferred</span>`}
          ${p.reopened ? `<span class="tag bad">Reopened</span>` : ""}${p.sla_breach ? `<span class="tag bad">SLA missed</span>` : ""}
          ${p.resolution_action ? `<span class="tag">${esc(p.resolution_action)}</span>` : ""}</div></li>`).join("")}</ul>`
        : `<p class="alt">None. First contact.</p>`}
    </div>
    ${a.onecase_cases.length ? `<div class="section"><p class="eyebrow">OneCase cases</p><ul class="past">${a.onecase_cases.map(c =>
      `<li><div class="row1"><span class="mono">${esc(c.case_id)}</span><span>${esc(c.status)}</span></div><div>${esc(c.owning_team)} · ${esc(c.channel)}</div></li>`).join("")}</ul></div>` : ""}`;
  billChart($("#bill-chart"), a.months);
}

// ------------------------------------------------------------------ boot
document.querySelectorAll(".seg button").forEach(b => b.addEventListener("click", () => !b.disabled && setMode(b.dataset.mode)));
$("#reset").addEventListener("click", async () => {
  await api("/reset", { method: "POST" });
  state.case = null; state.seen = new Set(); setMode("onecase");
  const lb = $(".seg [data-mode=legacy]"); lb.disabled = true; lb.title = "Create a case first";
  if (state.account) loadAccount(state.account.account.account_id);
});
addEventListener("resize", debounce(() => state.account && billChart($("#bill-chart"), state.account.months), 150));

state.meta = await api("/meta");
renderIntake();
// Preload the optional 3D stage while the agent is still on intake (never blocks, never throws).
(window.requestIdleCallback || setTimeout)(() => import("./gfx.js")
  .then(g => g.canUse3D() && import("./legacy3d.js").then(m => m.warmUp())).catch(() => {}));
