"""Phase 9: one-page value case, generated from assumptions.yaml and the scenario engine.

    python -m src.valuecase        writes docs/value_case.md
Refuses to run while any team estimate is still TBD, so numbers can't drift from the demo.
"""
from __future__ import annotations

import copy
import html
import re
import sys
from datetime import date

from . import scenario
from .config import DOCS, load_assumptions, val

REC = "recommended"


class TBDError(ValueError):
    pass


def tbd_keys(a: dict) -> list[str]:
    return [k for k, v in a["team_estimates"].items() if val(v) in (None, "TBD")]


def _m(x: float) -> str:
    if round(x) == 0:
        return "$0"
    return f"${x / 1e6:,.2f}M" if abs(x) >= 1e6 else f"${x / 1e3:,.0f}k"


def _scenario(a, sid):
    return next(s for s in a["scenarios"] if s["id"] == sid)


def benefits(a: dict, cal, levers: dict | None = None) -> dict:
    """Three-year benefit lines for the recommended package, plus monthly stream for payback."""
    s = _scenario(a, REC)
    lv = levers or s["levers"]
    te, uc = a["team_estimates"], a["unit_costs"]
    res = scenario.run(lv, a, cal, build_cost_keys=s["build_cost_keys"], run_cost_keys=s["run_cost_keys"])
    df = res["months"]

    # Handling saving split by lever: add levers one at a time; each line is the increment.
    parts, prev, acc = {}, 0.0, {}
    for key, label in [("transfers_removed", "Fewer transfers ($121 vs $68 a case)"),
                       ("info_only_first_contact", "Information-only answered at first contact"),
                       ("estimated_read_reduction", "Estimate complaints and corrections avoided")]:
        acc[key] = lv.get(key, 0)
        full = scenario.run(acc, a, cal)["summary"]["annual_saving_full_effect"]
        parts[label] = full - prev
        prev = full
    y1_ratio = res["summary"]["annual_saving_y1"] / res["summary"]["annual_saving_full_effect"]

    quarters, prob = float(val(te["penalty_quarters_at_risk"])), float(val(te["penalty_probability"]))
    penalty_total = quarters * val(uc["regulator_penalty_quarter"]) * prob
    # quarters at risk fall in order from quarter 1; each year takes up to 4 of them
    pen_years = [min(4, max(0, quarters - 4 * y)) * val(uc["regulator_penalty_quarter"]) * prob for y in range(3)]
    ai = val(uc["ai_pilot_year"])

    lines = []
    for label, full in parts.items():
        lines.append((label, [full * y1_ratio, full, full]))
    lines.append((f"Regulator penalty avoided ({quarters:g} quarters x $2.4M x {prob:.0%} probability)", pen_years))
    lines.append(("AI pilot not renewed (vs the client's AI-only plan)", [ai, ai, ai]))

    build = sum(float(val(te[k])) for k in s["build_cost_keys"])
    run_y = sum(float(val(te[k])) for k in s["run_cost_keys"])

    # Monthly benefit stream for payback (all benefits), 60 months
    monthly = []
    for m in range(1, 61):
        h = df["handling_saving"].iloc[m - 1] if m <= len(df) else df["handling_saving"].iloc[-1]
        q = (m - 1) // 3 + 1
        pen = (val(uc["regulator_penalty_quarter"]) * prob / 3) if q <= quarters else 0.0
        monthly.append(h + pen + ai / 12 - run_y / 12)
    cum, payback_all = 0.0, None
    for i, v in enumerate(monthly, 1):
        cum += v
        if cum >= build:
            payback_all = i
            break
    return {"res": res, "lines": lines, "build": build, "run_year": run_y, "penalty_total": penalty_total,
            "payback_all": payback_all, "payback_handling": res["summary"]["payback_months"]}


def sensitivity(a: dict, cal) -> list[tuple[str, str, object]]:
    """Payback (all benefits) when each key assumption is 50% worse."""
    base = benefits(a, cal)["payback_all"]
    rows = [("Base case", "", base)]
    te = a["team_estimates"]
    rec = _scenario(a, REC)["levers"]

    def worse_cost(key):
        b = copy.deepcopy(a)
        b["team_estimates"][key]["value"] = float(val(te[key])) * 1.5
        return benefits(b, cal)["payback_all"]

    def worse_te(key):
        b = copy.deepcopy(a)
        b["team_estimates"][key]["value"] = float(val(te[key])) * 0.5
        return benefits(b, cal)["payback_all"]

    def worse_lever(key):
        lv = dict(rec)
        lv[key] = lv.get(key, 0) * 0.5
        return benefits(a, cal, lv)["payback_all"]

    rows += [
        ("OneCase build cost", "+50%", worse_cost("onecase_build_cost")),
        ("Billing feedback loop cost", "+50%", worse_cost("billing_feedback_loop_cost")),
        ("OneCase run cost", "+50%", worse_cost("onecase_run_cost_year")),
        ("Transfers removed", f"{rec.get('transfers_removed', 0):.0%} -> {rec.get('transfers_removed', 0) / 2:.0%}",
         worse_lever("transfers_removed")),
        ("First-contact answers", f"{rec.get('info_only_first_contact', 0):.0%} -> "
         f"{rec.get('info_only_first_contact', 0) / 2:.0%}", worse_lever("info_only_first_contact")),
        ("Estimate complaints avoided", f"{rec.get('estimated_read_reduction', 0):.0%} -> "
         f"{rec.get('estimated_read_reduction', 0) / 2:.0%}", worse_lever("estimated_read_reduction")),
        ("Penalty quarters at risk", "-50%", worse_te("penalty_quarters_at_risk")),
        ("Penalty probability", "-50%", worse_te("penalty_probability")),
    ]
    return rows


def _mean_days(cal, transferred: int) -> float:
    cells = [cal.cells[(i, transferred)] for i in (0, 1)]
    return sum(c["days"] * c["share"] for c in cells) / sum(c["share"] for c in cells)


def build(a: dict | None = None) -> str:
    a = a or load_assumptions()
    missing = tbd_keys(a)
    if missing:
        raise TBDError("Set these in assumptions.yaml before generating the value case: " + ", ".join(missing))
    cal = scenario.calibrate(a)
    b = benefits(a, cal)
    s = b["res"]["summary"]
    rec = _scenario(a, REC)
    te = a["team_estimates"]
    pb = lambda v: f"{v} months" if v else "beyond 5 years"  # noqa: E731

    totals = [sum(l[1][y] for l in b["lines"]) for y in range(3)]
    out = [
        "# Northwind OneCase: value case",
        f"*Generated {date.today():%d %b %Y} by `python run.py valuecase` from assumptions.yaml and the scenario "
        "engine. Account-level data in the prototype is synthetic; every figure below comes from the data pack "
        "or a declared team estimate.*",
        "",
        f"**Ask:** {_m(b['build'])} to build, {_m(b['run_year'])} a year to run. "
        f"**Payback:** {pb(b['payback_all'])} on all benefits; {pb(b['payback_handling'])} on handling savings alone. "
        f"**Score:** {s['static']['score_month12']:.2f} by month 12 on the plan method "
        f"({s['static']['days_month12']:.1f} days); "
        + (f"4.0 in month {s['queue']['first_month_target_met']} if the backlog clears as history suggests "
           f"({s['queue']['days_month12']:.1f} days)." if s['queue']['first_month_target_met']
           else f"{s['queue']['score_month12']:.2f} backlog-aware."),
        "",
        "## 1. Cost",
        "| Line | Amount | Assumption |",
        "|---|---:|---|",
        f"| OneCase build (one-off) | {_m(float(val(te['onecase_build_cost'])))} | {te['onecase_build_cost']['source']} |",
        f"| Billing feedback loop (one-off) | {_m(float(val(te['billing_feedback_loop_cost'])))} | "
        f"{te['billing_feedback_loop_cost']['source']} |",
        f"| OneCase run (a year) | {_m(float(val(te['onecase_run_cost_year'])))} | {te['onecase_run_cost_year']['source']} |",
        "",
        "## 2. Benefit by year",
        "| Benefit | Year 1 | Year 2 | Year 3 |",
        "|---|---:|---:|---:|",
        *[f"| {label} | {_m(v[0])} | {_m(v[1])} | {_m(v[2])} |" for label, v in b["lines"]],
        f"| **Total** | **{_m(totals[0])}** | **{_m(totals[1])}** | **{_m(totals[2])}** |",
        f"| Net of run cost | {_m(totals[0] - b['run_year'])} | {_m(totals[1] - b['run_year'])} | "
        f"{_m(totals[2] - b['run_year'])} |",
        "",
        f"Year 1 handling savings ramp over {val(te['months_to_full_effect'])} months. Levers: "
        + ", ".join(f"{k.replace('_', ' ')} {v:.0%}" for k, v in rec["levers"].items()) + ". " + rec["note"],
        "",
        "## 3. Payback",
        f"{pb(b['payback_all'])} on all benefits, {pb(b['payback_handling'])} on handling savings only "
        "(build cost recovered from monthly net benefit; month 12 run rate continues after year 1).",
        "",
        "## 4. Assumptions",
        "| Number | Value | Source | Confidence |",
        "|---|---:|---|---|",
    ]
    bl, sm, uc = a["baseline"], a["score_model"], a["unit_costs"]
    out += [
        f"| Today: days to close, score, backlog | {val(bl['avg_days_to_close'])} days, {val(bl['regulator_score'])}, "
        f"{val(bl['open_backlog']):,} open | KPI + complaints files, Sep 2026 | High |",
        f"| Intake / closures a month | {val(bl['monthly_opened']):,} / {val(bl['monthly_closed']):,} | "
        "KPI file, last 6 months | High |",
        f"| Score model | {val(sm['intercept'])} {val(sm['slope_per_day'])} x days (4.0 = 19.0 days) | "
        "OLS on 24 KPI months, r = -0.98 | Medium (correlation) |",
        "| Unit costs | " + ", ".join(f"{k.replace('_', ' ')} ${val(v):,.{0 if float(val(v)).is_integer() else 2}f}"
                                      for k, v in uc.items()) + " | northwind_unit_costs.csv | High |",
        f"| Case mix | transferred {cal.transfer_share:.1%}, information-only {cal.info_share:.1%}, "
        f"estimate categories {cal.estimate_share:.1%}; transferred {_mean_days(cal, 1):.1f} vs "
        f"{_mean_days(cal, 0):.1f} days | northwind_complaints.csv, derived each run | High |",
        f"| Backlog effect | +{cal.queue_slope:.3f} days per open case (r = {cal.queue_fit_r:.2f}) | complaints + KPI "
        "files, non-transferred cases | Medium (correlation) |",
        "| Team estimates | " + "; ".join(f"{k.replace('_', ' ')} {val(v)}" for k, v in a["team_estimates"].items()
                                         if "cost" not in k or "unit" in k) +
        " | assumptions.yaml team_estimates; lever values in the recommended scenario | Low-Medium (team) |",
    ]

    sens = sensitivity(a, cal)
    out += ["", "## 5. Sensitivity: payback (all benefits) when one assumption is 50% worse",
            "| " + " | ".join(f"{n}{' ' + c if c else ''}" for n, c, _ in sens) + " |",
            "|" + "---:|" * len(sens),
            "| " + " | ".join(pb(p).replace(" months", " mo") for _, _, p in sens) + " |"]
    out += [
        "",
        "## 6. What this does not fix",
        "- **Aurora Billing (SYS-01), 1998 COBOL**: two developers understand the rating engine. OneCase reads from it; "
        "it does not replace it.",
        "- **Helix CIS (SYS-02)**: vendor support ends in 18 months. A separate programme is needed.",
        "- **Barrowdale and Dunmoor**: 0% smart meters, ~60% estimated reads. The bill check can only book a read there.",
        "- **Attrition** (Calderfield 40%+) is not addressed.",
        "",
        "## 7. Stop doing",
        "- Keep the AI pilot paused: containment fell 16% to 10%, repeat contact rose 31% to 45%, CSAT 2.6 to 2.0.",
        "- Pause the smart-meter rollout until billing uses the reads: penetration went 30% to 81% while estimated "
        "reads stayed flat.",
        "- Don't treat Calderfield hiring as the fix: its days to close and breach rate match the other regions.",
        "",
        "*Caveat: the score model is a correlation (r = -0.98 over 24 months). The transfer effect is a 24-month "
        "average applied to the latest month's 38.2 days.*",
    ]
    return "\n".join(out) + "\n"


def _inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)


def to_html(md: str) -> str:
    """Just enough markdown for this document, laid out to print on one A4 page."""
    body, rows, items = [], [], []

    def flush():
        if rows:
            head, *rest = [r for r in rows if not set(r.replace("|", "").strip()) <= set("-: ")]
            cells = lambda r, tag: "".join(f"<{tag}>{_inline(c.strip())}</{tag}>" for c in r.strip("|").split("|"))  # noqa: E731
            body.append(f"<table><tr>{cells(head, 'th')}</tr>" + "".join(f"<tr>{cells(r, 'td')}</tr>" for r in rest)
                        + "</table>")
            rows.clear()
        if items:
            body.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    cols = False
    for line in md.splitlines():
        if line.startswith("## 6."):   # sections 6 and 7 side by side on paper
            flush(); body.append("<div class='cols'><div>"); cols = True
        elif line.startswith("## 7.") and cols:
            flush(); body.append("</div><div>")
        elif line.startswith("*Caveat") and cols:
            flush(); body.append("</div></div>"); cols = False
        if line.startswith("|"):
            rows.append(line); continue
        if line.startswith("- "):
            items.append(line[2:]); continue
        flush()
        if line.startswith("# "):
            body.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.strip():
            body.append(f"<p>{_inline(line)}</p>")
    flush()
    if cols:
        body.append("</div></div>")
    css = ("@page{size:A4;margin:10mm}body{font:8pt/1.28 'Segoe UI',Arial,sans-serif;color:#0d1b26;max-width:190mm;"
           "margin:0 auto}h1{font:600 15pt Bahnschrift,'Segoe UI',sans-serif;margin:0 0 2px}h2{font:600 10pt Bahnschrift,"
           "'Segoe UI',sans-serif;margin:7px 0 2px;border-bottom:1px solid #d2dae0}p{margin:2px 0}table{border-collapse:"
           "collapse;width:100%;margin:2px 0}th,td{border-bottom:1px solid #e6ebee;padding:1px 4px;text-align:left;"
           "vertical-align:top}th{background:#e9eef1}td:first-child{white-space:nowrap}ul{margin:2px 0;padding-left:14px}code{font-size:8pt}"
           ".cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>OneCase value case</title>"
            f"<style>{css}</style></head><body>{''.join(body)}</body></html>")


def main(argv=None) -> int:
    try:
        text = build()
    except TBDError as e:
        print(f"Value case NOT generated. {e}", file=sys.stderr)
        return 2
    DOCS.mkdir(exist_ok=True)
    (DOCS / "value_case.md").write_text(text, encoding="utf-8")
    (DOCS / "value_case.html").write_text(to_html(text), encoding="utf-8")
    print("wrote docs/value_case.md and docs/value_case.html (print the HTML: one A4 page)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
