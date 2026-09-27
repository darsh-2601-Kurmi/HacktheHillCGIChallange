// Landing page (Start Bootstrap Creative layout): the About text, its three figures and the counts on the water and
// electricity photos. Every figure here comes from the data:
// /static/data/regions.json (built from region_month and complaint_360 by `python run.py data`) and /meta.
// If either request fails, the page keeps its static text.

const $ = s => document.querySelector(s);
const fmt = n => Number(n).toLocaleString("en-US");
const pct = v => `${Math.round(v * 100)}%`;
const pct1 = v => `${(v * 100).toFixed(1)}%`;

try {
  const data = await fetch("/static/data/regions.json").then(r => r.json());
  const meta = await fetch("/meta").then(r => r.json()).catch(() => null);
  const intake = Object.entries(data.transfer_by_intake);
  const zero = intake.find(([, v]) => v === 0), others = intake.filter(([, v]) => v > 0).map(([, v]) => v);
  const sum = key => data.regions.reduce((a, r) => a + r[key], 0);
  const month = ym => new Date(`${ym}-01T00:00:00`).toLocaleDateString("en-US", { month: "short", year: "numeric" });
  const period = data.period.replace(/\d{4}-\d{2}/g, month);             // "2024-10 to 2026-09" -> "Oct 2024 to Sep 2026"

  $("#lede").textContent = `Northwind logged ${fmt(data.total_complaints)} complaints from ${period}. ${pct1(data.transfer_share)} were ` +
    `passed from one system to another, and every handover lost the history. OneCase opens one case from any channel and keeps it to the end.`;
  $("#facts").innerHTML = [
    [`${data.days_transferred.toFixed(1)} vs ${data.days_not_transferred.toFixed(1)}`, "days to close, transferred vs not"],
    [pct(zero ? zero[1] : 0), `transfers from ${zero ? zero[0].split(" ").slice(1).join(" ") : "CaseTrack"} intake, vs ` +
      `${pct(Math.min(...others)).replace("%", "")}–${pct(Math.max(...others))} elsewhere`],
    [meta ? `${meta.baseline.regulator_score} → ${meta.baseline.target.toFixed(1)}` : "2.58 → 4.0", "regulator score today → target"],
  ].map(([b, s]) => `<div class="col-md-4 mt-4"><div class="h2 mb-1">${b}</div><div class="small text-white-75">${s}</div></div>`).join("");
  $("#n-water").textContent = fmt(sum("water"));
  $("#n-power").textContent = fmt(sum("electricity"));
} catch (e) {
  for (const id of ["#n-water", "#n-power"]) $(id).closest(".project-name").textContent =
    id === "#n-water" ? "Water-network complaints" : "Electricity and billing complaints";
}
