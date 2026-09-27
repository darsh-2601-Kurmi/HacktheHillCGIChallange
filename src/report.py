"""Diagnosis report: the whole Northwind story as one self-contained, multi-page HTML file (replaces Power BI).

    python run.py report        writes docs/report.html (also runs in `python run.py data`)

Reads the exports exactly as the pipeline writes them (data/exports/*.csv) plus the raw AI pilot file; no database,
no network. Charts are inline SVG from src/svgchart.py. A small inline script adds page tabs, tooltips, the
light/dark switch and the what-if levers; without it every page still shows, one after another.
Open the file straight from disk: nothing loads from anywhere else.
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from . import svgchart as sc
from .config import DOCS, EXPORTS, RAW, RAW_FILES, REGIONS, SMART_REGIONS

OUT = DOCS / "report.html"
esc = sc.esc

SCEN_ORDER = ["everything_max", "recommended", "routing_fix", "client_ai_plan", "status_quo"]
SCEN_SHORT = {"status_quo": "Status quo", "client_ai_plan": "Client's AI plan", "routing_fix": "Routing fix only",
              "recommended": "Recommended", "everything_max": "Everything at max"}
SCEN_CLS = {"recommended": "s-b", "routing_fix": "s-a", "everything_max": "s-good", "client_ai_plan": "s-pink",
            "status_quo": "s-sq"}
LEVERS = [("t", "transfers_removed", "Transfers removed", "OneCase: one case from intake to close, no re-keying"),
          ("i", "info_only_first_contact", "Answered at first contact", "Information-only complaints closed on the spot"),
          ("e", "estimated_read_reduction", "Estimate complaints avoided", "Bill on smart reads; fix estimates at source"),
          ("a", "calderfield_agents_restored", "Calderfield agents restored", "Rehire the agents Calderfield lost")]


# --------------------------------------------------------------------------- formatting
def n0(x):
    return f"{x:,.0f}"


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def d1(x):
    return f"{x:.1f}"


def d2(x):
    return f"{x:.2f}"


def money(x):
    return f"${x:,.0f}"


def minus(s: str) -> str:
    return s.replace("-", "−")


def mlong(m: str) -> str:
    return pd.Period(m, "M").strftime("%b %Y")


def mshort(m: str) -> str:
    return pd.Period(m, "M").strftime("%b %y")


# --------------------------------------------------------------------------- the numbers
def facts(exports=EXPORTS, raw=RAW) -> dict:
    """Every number the report shows, computed from the files as loaded (no transforms on disk)."""
    c = pd.read_csv(exports / "complaint_360.csv", parse_dates=["date_opened"])
    rm = pd.read_csv(exports / "region_month.csv", dtype={"month": str})
    bm = pd.read_csv(exports / "backlog_month.csv", dtype={"month": str}).sort_values("month")
    scn = pd.read_csv(exports / "scenarios.csv", dtype={"month": str})
    lg = pd.read_csv(exports / "lever_grid.csv")
    cal = pd.read_csv(exports / "calibration.csv").set_index("name")["value"]
    ai = pd.read_csv(raw / RAW_FILES["ai_pilot"], dtype={"month": str}).sort_values("month")

    F: dict = {"rows": {"complaint_360": len(c), "region_month": len(rm), "backlog_month": len(bm),
                        "scenarios": len(scn), "lever_grid": len(lg), "calibration": len(cal), "ai_pilot": len(ai)}}
    t = c["transferred_between_systems"].eq(1)
    F["complaints"], F["open"], F["transferred"] = len(c), int(c["is_open"].sum()), int(t.sum())
    F["transfer_rate"] = float(t.mean())
    F["days_all"] = float(c["days_to_close"].mean())
    F["breach_all"] = float(c["sla_breach"].mean())
    F["handling_cost"] = float(c["handling_unit_cost"].sum())
    F["period"] = (mlong(bm["month"].iloc[0]), mlong(bm["month"].iloc[-1]))

    def grp(d):
        return {"n": len(d), "days": float(d["days_to_close"].mean()), "breach": float(d["sla_breach"].mean()),
                "reopen": float(d["reopened"].mean()), "cost": float(d["handling_unit_cost"].mean())}
    F["cmp"] = {"t": grp(c[t]), "nt": grp(c[~t])}

    it = (c.groupby(["source_system", "source_system_name"])["transferred_between_systems"].agg(["mean", "size"])
          .reset_index().sort_values("mean"))
    F["intake"] = [{"sys": r.source_system, "name": r.source_system_name, "rate": float(r["mean"]), "n": int(r["size"])}
                   for _, r in it.iterrows()]
    F["casetrack_note"] = c.loc[c["source_system"] == "SYS-04", "source_system_notes"].iloc[0]

    c["quarter"] = c["date_opened"].dt.year.astype(str) + " Q" + c["date_opened"].dt.quarter.astype(str)

    def rate_by(col, natural=False):
        g = c.groupby(col)["transferred_between_systems"].agg(["mean", "size"])
        g = g.sort_index() if natural else g.sort_values("size", ascending=False)
        return [{"label": k, "rate": float(r["mean"]), "n": int(r["size"])} for k, r in g.iterrows()]
    F["by"] = {"category": rate_by("category"), "channel": rate_by("channel"),
               "priority": rate_by("priority", True), "quarter": rate_by("quarter", True)}
    flat = [r["rate"] for rows in F["by"].values() for r in rows]
    F["flat_lo"], F["flat_hi"] = min(flat), max(flat)

    cat = (c.groupby("category").agg(n=("complaint_id", "size"), grp=("category_group", "first"))
           .sort_values("n", ascending=False))
    F["categories"] = [{"label": k, "n": int(r["n"]), "grp": r["grp"]} for k, r in cat.iterrows()]
    F["bill_meter_share"] = float(c["category_group"].isin(["Billing", "Metering"]).mean())
    F["estimate_driven"] = float(c["estimate_driven"].mean())
    bill = c[c["category_group"] == "Billing"]
    F["billing_fixed"] = float(bill["resolution_action"].isin(
        ["Bill corrected and re-issued", "Refund or credit applied"]).mean())

    io = c["resolvable_by_information_only"].eq(1)
    F["info"] = {"n": int(io.sum()), "share": float(io.sum() / len(c)),
                 "days": float(c.loc[io, "days_to_close"].mean()),
                 "transfer": float(c.loc[io, "transferred_between_systems"].mean())}

    x, y = bm["avg_days_to_close"], bm["regulator_satisfaction_score_of_5"]
    slope, intercept = np.polyfit(x, y, 1)
    F["score"] = {"months": bm["month"].tolist(), "score": y.tolist(), "days": x.tolist(),
                  "backlog": bm["backlog_end"].tolist(), "slope": float(slope), "intercept": float(intercept),
                  "r": float(np.corrcoef(x, y)[0, 1]), "days_for_4": float((4 - intercept) / slope),
                  "r_backlog": float(np.corrcoef(bm["backlog_avg"], x)[0, 1]),
                  "fell_every_month": bool((y.diff().dropna() < 0).all())}
    F["queue_slope"], F["queue_r"] = float(cal["queue_slope"]), float(cal["queue_fit_r"])

    sm = (rm[rm["region"].isin(SMART_REGIONS)].groupby("month")[["smart_meter_penetration", "estimated_read_rate"]]
          .mean().sort_index())
    last_m = rm["month"].max()
    latest = rm[rm["month"] == last_m].set_index("region")
    F["meters"] = {"months": sm.index.tolist(), "pen": sm["smart_meter_penetration"].tolist(),
                   "est": sm["estimated_read_rate"].tolist(),
                   "latest": sorted(({"region": r, "est": float(latest.loc[r, "estimated_read_rate"]),
                                      "pen": float(latest.loc[r, "smart_meter_penetration"])} for r in REGIONS),
                                    key=lambda d: -d["est"]),
                   "last_month": mlong(last_m)}

    ag = rm.pivot(index="month", columns="region", values="agent_fte").sort_index()
    since = c[c["date_opened"] >= "2026-03-01"].groupby("region").agg(
        days=("days_to_close", "mean"), breach=("sla_breach", "mean"), n=("complaint_id", "size"),
        transfer=("transferred_between_systems", "mean"))
    F["staff"] = {"months": ag.index.tolist(), "agents": {r: ag[r].tolist() for r in REGIONS},
                  "since": {r: {k: float(v) for k, v in since.loc[r].items()} for r in REGIONS}}

    F["ai"] = {k: ai[k].tolist() for k in ai.columns}

    S = {}
    for sid, g in scn.groupby("scenario_id", sort=False):
        g = g.sort_values("month_index")
        m12 = g[g["month_index"] == 12].iloc[0]

        def first(col):
            hit = g.loc[g[col] >= 4, "month_index"]
            return int(hit.min()) if len(hit) else None
        S[sid] = {"name": g["scenario_name"].iloc[0], "months": g["month"].tolist(),
                  "static": g["score_static"].tolist(), "queue": g["score_queue"].tolist(),
                  "m12_static": float(m12["score_static"]), "m12_queue": float(m12["score_queue"]),
                  "m12_days": float(m12["avg_days_static"]), "m12_backlog": float(m12["backlog"]),
                  "saving_year": float(m12["handling_saving"] * 12),
                  "reach_static": first("score_static"), "reach_queue": first("score_queue")}
    F["scen"] = S

    def key(r):
        return (f"{round(r.transfers_removed * 100)}|{round(r.info_only_first_contact * 100)}|"
                f"{round(r.estimated_read_reduction * 100)}|{int(r.calderfield_agents_restored)}")
    F["grid"] = {
        "rows": {key(r): [round(r.score_static_month12, 3), round(r.score_queue_month12, 3),
                          round(r.avg_days_month12, 2), round(r.backlog_month12), round(r.annual_saving_full_effect)]
                 for r in lg.itertuples()},
        "levels": {k: sorted({round(v * 100) if k != "a" else int(v) for v in lg[col]}) for k, col, _, _ in LEVERS},
    }
    return F


# --------------------------------------------------------------------------- building blocks
def kpi(label, value, sub="", cls=""):
    s = f'<div class="k-s">{sub}</div>' if sub else ""
    return f'<div class="kpi {cls}"><div class="k-l">{label}</div><div class="k-v">{value}</div>{s}</div>'


def card(title, body, *, sub="", src="", span=6, cls=""):
    s = f'<p class="sub">{sub}</p>' if sub else ""
    f = f'<p class="src">{src}</p>' if src else ""
    return (f'<figure class="card span-{span} {cls}"><figcaption><h3>{title}</h3>{s}</figcaption>'
            f'<div class="viz">{body}</div>{f}</figure>')


def table(head, rows, *, cls="", num_from=1, row_cls=None):
    th = "".join(f'<th{" class=n" if i >= num_from else ""}>{h}</th>' for i, h in enumerate(head))
    trs = []
    for j, r in enumerate(rows):
        rc = f' class="{row_cls[j]}"' if row_cls and row_cls[j] else ""
        tds = "".join(f'<td{" class=n" if i >= num_from else ""}>{v}</td>' for i, v in enumerate(r))
        trs.append(f"<tr{rc}>{tds}</tr>")
    return f'<table class="tbl {cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def page(pid, tab, eyebrow, title, lede, body):
    return (f'<section class="page" id="{pid}" data-title="{esc(tab)}" aria-labelledby="{pid}-h">'
            f'<header class="p-head"><p class="eyebrow">{eyebrow}</p><h2 id="{pid}-h">{title}</h2>'
            f'<p class="lede">{lede}</p></header>{body}</section>')


# --------------------------------------------------------------------------- pages
def p_summary(F):
    s = F["score"]
    kp = "".join([
        kpi("Complaints", n0(F["complaints"]), f'{F["period"][0]} to {F["period"][1]}'),
        kpi("Still open", n0(F["open"]), f'at the end of {F["period"][1]}'),
        kpi("Passed between systems", pct(F["transfer_rate"]), f'{n0(F["transferred"])} complaints'),
        kpi("Days to close", d1(s["days"][-1]), f'{F["period"][1]}, up from {d1(s["days"][0])}', "bad"),
        kpi("Regulator score", d2(s["score"][-1]), f'of 5, down from {d2(s["score"][0])}', "bad"),
        kpi("Days needed for 4.0", d1(s["days_for_4"]), "from the score model", "good"),
    ])
    others = [r["rate"] for r in F["intake"] if r["sys"] != "SYS-04"]
    m, st = F["meters"], F["staff"]
    cal_ag = st["agents"]["Calderfield"]
    rec = F["scen"]["recommended"]
    finds = [
        ("p-score", "The score follows the days", minus(f'r = {s["r"]:.2f}'),
         f'The score fell {"every month" if s["fell_every_month"] else "steadily"}, {d2(s["score"][0])} → '
         f'{d2(s["score"][-1])}, as days to close rose {d1(s["days"][0])} → {d1(s["days"][-1])}. '
         f'4.0 needs about {s["days_for_4"]:.0f} days.'),
        ("p-transfers", "Transfers come from the intake system",
         f'0% vs {min(others) * 100:.0f}–{max(others) * 100:.0f}%',
         f'CaseTrack never passes a complaint on; the other three intake systems pass on almost half. '
         f'A transfer adds {d1(F["cmp"]["t"]["days"] - F["cmp"]["nt"]["days"])} days.'),
        ("p-billing", "Billing ignores the smart meters", f'{pct(m["pen"][0], 0)} → {pct(m["pen"][-1], 0)}',
         f'Smart meters spread in four regions, yet estimated bills stayed at {pct(m["est"][0], 0)} to '
         f'{pct(m["est"][-1], 0)}. {pct(F["bill_meter_share"], 0)} of complaints are billing and metering.'),
        ("p-answers", "1 in 4 only needed an answer", pct(F["info"]["share"]),
         f'They still took {d1(F["info"]["days"])} days. The 2025 AI assistant pilot got worse every month.'),
        ("p-calderfield", "Calderfield is not the cause", f'{cal_ag[0]:.0f} → {cal_ag[-1]:.0f} agents',
         "It lost half its agents, yet its days to close match every other region."),
        ("p-reach", "4.0 needs the backlog to clear", f'4.0 by month {rec["reach_queue"]}',
         f'Per-case fixes alone stop at {d2(rec["m12_static"])} (plan method). If the backlog clears as history '
         f'suggests, the recommended package reaches 4.0 in month {rec["reach_queue"]}.'),
    ]
    fl = "".join(f'<a class="find" href="#{pid}"><span class="f-n">{i}</span><span class="f-t">{t}</span>'
                 f'<span class="f-v">{v}</span><span class="f-x">{x}</span><span class="f-go">Open page →</span></a>'
                 for i, (pid, t, v, x) in enumerate(finds, 1))
    lede = (f'{n0(F["complaints"])} complaints over 24 months. A complaint passed from one system to another takes '
            f'{d1(F["cmp"]["t"]["days"])} days to close instead of {d1(F["cmp"]["nt"]["days"])}, and whether it '
            f'gets passed on depends on the system that took it in. The six findings below lead to one fix: '
            f'one case from first contact to close.')
    body = (f'<div class="kpis">{kp}</div><h3 class="sec">Six findings</h3><div class="finds">{fl}</div>'
            f'<p class="howto">Use the tabs or the ← → keys to move between pages. Point at any bar, line or dot '
            f'for its values.</p>')
    return page("p-summary", "Summary", f'Northwind Utilities · complaints · {F["period"][0]} to {F["period"][1]}',
                "The regulator score fell every month for two years, in step with how long complaints take to close",
                lede, body)


def p_score(F):
    s = F["score"]
    months = s["months"]
    r_txt = minus(f'r = {s["r"]:.2f}')
    score = sc.line_chart(months, [{"key": "score", "name": "Score", "values": s["score"], "cls": "s-a", "end": "Score"}],
                          fmt=d1, tip_fmt=d2, refs=[(4, "Target 4.0")], xtick=mshort, xlong=mlong,
                          label="Regulator score by month", right=96, w=610)
    days = sc.line_chart(months, [{"key": "days", "name": "Days to close", "values": s["days"], "cls": "s-b",
                                   "end": "Days"}],
                         fmt=lambda v: f"{v:.0f}", tip_fmt=d1, zero=True, xtick=mshort, xlong=mlong,
                         refs=[(s["days_for_4"], f'Needed for 4.0: {d1(s["days_for_4"])}')],
                         label="Average days to close by month", right=96, w=610)
    pts = [{"x": d, "y": v, "tip_title": mlong(m)} for m, d, v in zip(months, s["days"], s["score"])]
    fit_txt = minus(f'score = {s["intercept"]:.3f} - {abs(s["slope"]):.3f} × days')
    scat = sc.scatter(pts, x_fmt=lambda v: f"{v:.0f}", y_fmt=d2, label="Score against days to close",
                      x_title="Average days to close", y_title="Score (of 5)", x_domain=(0, 40), y_domain=(2.5, 5),
                      fit=(s["slope"], s["intercept"]), fit_text=fit_txt,
                      callouts=[(0, mlong(months[0]), 10, 4), (len(pts) - 1, mlong(months[-1]), -10, 20)],
                      w=720, h=330)
    back = sc.line_chart(months, [{"key": "b", "name": "Open complaints", "values": s["backlog"], "cls": "s-c",
                                   "end": "Open"}],
                         fmt=n0, zero=True, xtick=mshort, xlong=mlong, label="Open backlog by month", right=96,
                         w=500, h=330, tick_every=6)
    lede = (f'The score fell {"every single month" if s["fell_every_month"] else "steadily"}, from '
            f'{d2(s["score"][0])} to {d2(s["score"][-1])}, while average days to close rose from '
            f'{d1(s["days"][0])} to {d1(s["days"][-1])}. A straight line fits the two closely '
            f'({r_txt}), so reaching 4.0 means closing complaints in about '
            f'{d1(s["days_for_4"])} days.')
    body = ('<div class="grid">'
            + card(f'Regulator score fell every month: {d2(s["score"][0])} → {d2(s["score"][-1])}', score,
                   sub="Regulator satisfaction score (of 5), by month", src="Source: monthly KPI file")
            + card(f'Days to close: {d1(s["days"][-1])} now, {d1(s["days_for_4"])} needed for 4.0', days,
                   sub="Average days to close, complaints closed that month", src="Source: monthly KPI file")
            + card(f'The score tracks days to close ({r_txt})', scat, span=7,
                   sub="Each dot is one month. Line: least-squares fit over 24 months",
                   src="A close correlation over 24 months, not proof of cause on its own.")
            + card(f'The open backlog grew from {n0(s["backlog"][0])} to {n0(s["backlog"][-1])}', back, span=5,
                   sub=f'Open complaints at month end. Days to close move with it (r = {s["r_backlog"]:.2f})',
                   src="The backlog-aware projection on Reaching 4.0 relies on this link.")
            + "</div>")
    return page("p-score", "The score", "Finding 1 · The score",
                "The regulator score follows days to close", lede, body)


def p_transfers(F):
    t, nt = F["cmp"]["t"], F["cmp"]["nt"]
    rows = [{"label": f'{r["name"]} ({r["sys"]})', "value": r["rate"], "cls": "s-a" if r["sys"] == "SYS-04" else "s-b",
             "measure": "Transferred", "tip": [("Complaints taken in", n0(r["n"]))]} for r in F["intake"]][::-1]
    intake = sc.hbar_chart(rows, fmt=lambda v: f"{v * 100:.0f}%", tip_fmt=pct, domain=(0, 0.5), label_w=210,
                           row_h=40, label="Share transferred by intake system", w=610)
    others = [r["rate"] for r in F["intake"] if r["sys"] != "SYS-04"]
    note = (f'<blockquote class="note">“{esc(F["casetrack_note"])}”'
            f'<cite>CaseTrack (SYS-04) system note, in the data pack</cite></blockquote>')
    diff = [
        ("Complaints", n0(t["n"]), n0(nt["n"]), ""),
        ("Average days to close", d1(t["days"]), d1(nt["days"]), f'+{d1(t["days"] - nt["days"])} days'),
        ("Missed the SLA", pct(t["breach"]), pct(nt["breach"]), f'+{(t["breach"] - nt["breach"]) * 100:.1f} pts'),
        ("Reopened", pct(t["reopen"]), pct(nt["reopen"]), f'+{(t["reopen"] - nt["reopen"]) * 100:.1f} pts'),
        ("Handling cost per complaint", money(t["cost"]), money(nt["cost"]), f'+{money(t["cost"] - nt["cost"])}'),
    ]
    cmp = table(["", "Transferred", "Not transferred", "Difference"], diff, cls="cmp")
    head = {"category": "Category", "channel": "Channel", "priority": "Priority", "quarter": "Quarter opened"}
    multi = []
    for k, rows_ in F["by"].items():
        ch = sc.hbar_chart([{"label": r["label"], "value": r["rate"], "cls": "s-a", "measure": "Transferred",
                             "tip": [("Complaints", n0(r["n"]))]} for r in rows_],
                           fmt=lambda v: f"{v * 100:.0f}%", tip_fmt=pct, domain=(0, 0.5), n_ticks=2,
                           refs=[(F["transfer_rate"], "")], label=f"Share transferred by {head[k].lower()}",
                           w=620, label_w=220, row_h=27, right=56, value_col=True)
        multi.append(f'<div class="mult"><h4>{head[k]}</h4>{ch}</div>')
    lede = (f'{pct(F["transfer_rate"])} of complaints were passed from one system to another. Split by category, '
            f'channel, priority or quarter, that rate barely moves ({F["flat_lo"] * 100:.0f}–{F["flat_hi"] * 100:.0f}%). '
            f'Split by the system that took the complaint in, it is 0% for CaseTrack and '
            f'{min(others) * 100:.0f}–{max(others) * 100:.0f}% for the other three.')
    body = ('<div class="grid">'
            + card(f'CaseTrack 0%, the other intake systems {min(others) * 100:.0f}–{max(others) * 100:.0f}%',
                   intake + note, sub="Share of complaints transferred, by the system that took the complaint in")
            + card(f'A transfer adds {d1(t["days"] - nt["days"])} days, and more breaches, reopens and cost', cmp,
                   sub="All 25,416 complaints; days to close counts closed complaints only",
                   src="Handling cost: unit costs from the data pack, $121 for a transferred complaint, $68 otherwise.")
            + card(f'Everything else is flat: {F["flat_lo"] * 100:.0f}–{F["flat_hi"] * 100:.0f}% whatever the complaint',
                   f'<div class="multis">{"".join(multi)}</div>', span=12,
                   sub=f'Share transferred, same 0–50% scale in every panel. Dashed line: all complaints '
                       f'({pct(F["transfer_rate"])})')
            + "</div>")
    return page("p-transfers", "Transfers", "Finding 2 · Transfers",
                "Whether a complaint gets transferred depends on the system that took it in", lede, body)


def p_billing(F):
    m = F["meters"]
    hl = {"Billing", "Metering"}
    cats = sc.hbar_chart([{"label": r["label"], "value": r["n"], "cls": "s-b" if r["grp"] in hl else "s-m",
                           "measure": "Complaints", "tip": [("Share", pct(r["n"] / F["complaints"]))]}
                          for r in F["categories"]],
                         fmt=n0, label="Complaints by category", label_w=220, row_h=30, right=60, w=720)
    lines = sc.line_chart(m["months"], [
        {"key": "pen", "name": "Homes with a smart meter", "values": m["pen"], "cls": "s-a", "end": "Smart meters"},
        {"key": "est", "name": "Bills on an estimate", "values": m["est"], "cls": "s-b", "end": "Estimated bills"}],
        fmt=lambda v: f"{v * 100:.0f}%", tip_fmt=lambda v: pct(v), end_fmt=lambda v: f"{v * 100:.0f}%",
        domain=(0, 1), xtick=mshort, xlong=mlong, label="Smart-meter share and estimated-bill share by month",
        right=150, w=720)
    cols = sc.column_chart([{"label": r["region"], "value": r["est"], "cls": "s-b" if r["est"] >= 0.5 else "s-a",
                             "measure": "Bills on an estimate", "tip": [("Homes with a smart meter", pct(r["pen"], 0))]}
                            for r in m["latest"]],
                           fmt=lambda v: f"{v * 100:.0f}%", tip_fmt=pct, domain=(0, 0.8), w=500, h=300,
                           label=f'Estimated-bill share by region, {m["last_month"]}')
    kp = ('<div class="kstack">'
          + kpi("Complaints about bills and meter reads", pct(F["bill_meter_share"], 0),
                "billing disputes, estimated reads, no read taken", "bad")
          + kpi("Billing complaints ending in a correction or refund", pct(F["billing_fixed"], 0),
                "the customer was right more often than not")
          + kpi(f'Bills on an estimate, smart-meter regions, {m["last_month"]}', pct(m["est"][-1], 0),
                f'with smart meters in {pct(m["pen"][-1], 0)} of homes', "bad")
          + "</div>")
    top2 = [r["region"] for r in m["latest"] if r["est"] >= 0.5]
    lede = (f'{pct(F["bill_meter_share"], 0)} of complaints are about bills and meter reads, and '
            f'{pct(F["billing_fixed"], 0)} of billing complaints end with the bill corrected or refunded. In the four '
            f'smart-meter regions, smart meters went from {pct(m["pen"][0], 0)} to {pct(m["pen"][-1], 0)} of homes, '
            f'yet the share of bills on an estimate did not fall ({pct(m["est"][0], 0)} → {pct(m["est"][-1], 0)}).')
    body = ('<div class="grid">'
            + card(f'Billing and metering: {pct(F["bill_meter_share"], 0)} of complaints', cats, span=7,
                   sub="Complaints by category, all 24 months. Orange: billing and metering")
            + card("Behind the billing complaints", kp, span=5)
            + card(f'Smart meters {pct(m["pen"][0], 0)} → {pct(m["pen"][-1], 0)}; estimated bills '
                   f'{pct(m["est"][0], 0)} → {pct(m["est"][-1], 0)}', lines, span=7,
                   sub="Average of the four smart-meter regions (Ashford, Calderfield, Eastmarch, Fenwick), by month",
                   src="Billing (Aurora, 1998) takes reads by nightly batch file; smart reads don't reach the bill.")
            + card(f'{" and ".join(top2)}: no smart meters, {pct(max(r["est"] for r in m["latest"]), 0)} estimated',
                   cols, span=5, sub=f'Share of bills on an estimate, by region, {m["last_month"]}')
            + "</div>")
    return page("p-billing", "Billing", "Finding 3 · Billing and meters",
                "Billing and metering drive the volume, and billing still ignores the smart meters", lede, body)


def p_answers(F):
    io, ai = F["info"], F["ai"]
    kp = "".join([
        kpi("Complaints that only needed an answer", n0(io["n"]), "resolvable with information alone"),
        kpi("Share of all complaints", pct(io["share"]), "about 1 in 4"),
        kpi("Average days to close them", d1(io["days"]), f'all complaints: {d1(F["days_all"])}', "bad"),
        kpi("Transferred between systems", pct(io["transfer"]), f'all complaints: {pct(F["transfer_rate"])}', "bad"),
    ])
    rates = sc.line_chart(ai["month"], [
        {"key": "c", "name": "Fully contained", "values": ai["fully_contained_rate"], "cls": "s-a",
         "end": "Contained"},
        {"key": "r", "name": "Repeat contact in 7 days", "values": ai["repeat_contact_within_7_days_rate"],
         "cls": "s-b", "end": "Repeat contact"},
        {"key": "p", "name": "Complaint after session", "values": ai["complaint_raised_after_session_rate"],
         "cls": "s-c", "end": "Complaint after"}],
        fmt=lambda v: f"{v * 100:.0f}%", tip_fmt=pct, end_fmt=pct, domain=(0, 0.5), xtick=mshort, xlong=mlong,
        tick_every=2, right=170, w=720, label="AI assistant pilot outcomes by month")
    csat = sc.line_chart(ai["month"], [{"key": "s", "name": "Assistant CSAT", "values": ai["assistant_csat_of_5"],
                                        "cls": "s-pink", "end": "CSAT"}],
                         fmt=lambda v: f"{v:.1f}", tip_fmt=d2, domain=(1.5, 3), xtick=mshort, xlong=mlong,
                         tick_every=2, right=90, w=500, h=320, label="AI assistant CSAT by month")
    c0, c1 = ai["fully_contained_rate"][0], ai["fully_contained_rate"][-1]
    r0, r1 = ai["repeat_contact_within_7_days_rate"][0], ai["repeat_contact_within_7_days_rate"][-1]
    lede = (f'{n0(io["n"])} complaints ({pct(io["share"])}) could have been closed with information alone. They '
            f'still took {d1(io["days"])} days and were transferred as often as any other ({pct(io["transfer"])}). '
            f'The 2025 AI assistant pilot, meant to answer these, got worse every month: fewer sessions contained, '
            f'more customers coming back.')
    body = (f'<div class="kpis">{kp}</div><div class="grid" style="margin-top:16px">'
            + card(f'AI pilot: contained {pct(c0)} → {pct(c1)}, repeat contact {pct(r0)} → {pct(r1)}', rates, span=7,
                   sub="Share of assistant sessions, by month, 2025",
                   src="The assistant could not see a bill breakdown or the case history.")
            + card(f'Assistant CSAT {d2(ai["assistant_csat_of_5"][0])} → {d2(ai["assistant_csat_of_5"][-1])}', csat,
                   span=5, sub="Customer satisfaction with the assistant (of 5), by month, 2025",
                   src="Separate chart: CSAT is on a 1–5 scale, not a percentage.")
            + "</div>")
    return page("p-answers", "Answers & AI", "Finding 4 · Answers and the AI pilot",
                "A quarter of complaints only needed an answer, and the AI pilot made things worse", lede, body)


def p_calderfield(F):
    st = F["staff"]
    series = [{"key": r, "name": r, "values": st["agents"][r], "cls": "s-b" if r == "Calderfield" else "s-ctx",
               "weight": "bold" if r == "Calderfield" else "thin", "end": r} for r in REGIONS]
    series.sort(key=lambda s: s["key"] == "Calderfield")          # Calderfield drawn last, on top
    agents = sc.line_chart(st["months"], series, fmt=n0, zero=True, xtick=mshort, xlong=mlong, right=150, w=720,
                           label="Agents by region by month")
    sin = st["since"]
    cols = sc.column_chart([{"label": r, "value": sin[r]["days"], "cls": "s-b" if r == "Calderfield" else "s-m",
                             "measure": "Average days to close",
                             "tip": [("Missed the SLA", pct(sin[r]["breach"])), ("Complaints", n0(sin[r]["n"]))]}
                            for r in REGIONS], fmt=lambda v: f"{v:.0f}", vfmt=d1, tip_fmt=d1, domain=(0, 40),
                           w=500, h=300,
                           label="Average days to close since March 2026 by region")
    days = [sin[r]["days"] for r in REGIONS]
    ag = st["agents"]["Calderfield"]
    rows = [[r, n0(st["agents"][r][0]), n0(st["agents"][r][-1]),
             f'{(st["agents"][r][-1] / st["agents"][r][0] - 1) * 100:+.0f}%', n0(sin[r]["n"]), d1(sin[r]["days"]),
             pct(sin[r]["breach"]), pct(sin[r]["transfer"])] for r in REGIONS]
    tbl = table(["Region", f'Agents {mshort(st["months"][0])}', f'Agents {mshort(st["months"][-1])}', "Change",
                 "Complaints since Mar 26", "Days to close", "Missed SLA", "Transferred"], rows,
                row_cls=["hl" if r == "Calderfield" else "" for r in REGIONS])
    lede = (f'Calderfield went from {ag[0]:.0f} agents to {ag[-1]:.0f}, most of it in March 2026. If staffing drove '
            f'the decline, Calderfield would stand out after March. It doesn\'t: complaints opened since March '
            f'take {d1(min(days))}–{d1(max(days))} days to close in every region, Calderfield '
            f'{d1(sin["Calderfield"]["days"])}.')
    body = ('<div class="grid">'
            + card(f'Calderfield lost half its agents ({ag[0]:.0f} → {ag[-1]:.0f})…', agents, span=7,
                   sub="Contact-centre agents (FTE) by region, by month", src="Source: contact-centre staffing file")
            + card(f'…yet its days to close match every region ({d1(min(days))}–{d1(max(days))})', cols, span=5,
                   sub="Average days to close, complaints opened since March 2026")
            + card("Region by region since March 2026", tbl, span=12,
                   sub="The regions with full staff have the same days to close, breach rate and transfer rate")
            + "</div>")
    return page("p-calderfield", "Calderfield", "Finding 5 · Staffing",
                "Calderfield lost half its agents, and its results match every other region", lede, body)


def p_reach(F):
    S = F["scen"]
    months = S["status_quo"]["months"]

    def chart(col, label):
        ser = [{"key": k, "name": SCEN_SHORT[k], "values": S[k][col], "cls": SCEN_CLS[k],
                "weight": "bold" if k == "recommended" else None, "end": SCEN_SHORT[k]} for k in SCEN_ORDER[::-1]]
        return sc.line_chart(months, ser, fmt=lambda v: f"{v:.0f}", tip_fmt=d2, domain=(1, 5), n_ticks=4,
                             refs=[(4, "Target 4.0")], xtick=mshort, xlong=mlong, tick_every=3, right=178, w=610,
                             label=label)
    best_static = max(S[k]["m12_static"] for k in S)
    rec = S["recommended"]
    rows, rc = [], []
    for k in SCEN_ORDER:
        s = S[k]
        rq = f'Month {s["reach_queue"]}' if s["reach_queue"] else "Not reached"
        rows.append([f'<b>{esc(SCEN_SHORT[k])}</b><small>{esc(s["name"])}</small>', d2(s["m12_static"]),
                     f'<span class="{"ok" if s["m12_queue"] >= 4 else ""}">{d2(s["m12_queue"])}</span>', rq,
                     n0(s["m12_backlog"]), money(s["saving_year"])])
        rc.append("hl" if k == "recommended" else "")
    tbl = table(["Scenario", "Score, month 12<br><small>plan method</small>",
                 "Score, month 12<br><small>backlog-aware</small>", "Reaches 4.0<br><small>backlog-aware</small>",
                 "Open backlog<br><small>month 12</small>", "Handling saving<br><small>a year</small>"], rows,
                row_cls=rc, cls="scen")
    lede = (f'The scenario engine projects the next 12 months two ways. The <b>plan method</b> subtracts per-case '
            f'savings from today\'s days to close: even every fix at maximum reaches only {d2(best_static)}. The '
            f'<b>backlog-aware</b> view also lets days fall as the open backlog clears, the way days have tracked the '
            f'backlog for 24 months: the recommended package reaches 4.0 in month {rec["reach_queue"]}.')
    body = ('<div class="grid">'
            + card(f'Plan method: nothing reaches 4.0 (best {d2(best_static)})', chart("static", "Plan-method score"),
                   sub="Regulator score, next 12 months, per-case savings only")
            + card(f'Backlog-aware: the recommended package reaches 4.0 in month {rec["reach_queue"]}',
                   chart("queue", "Backlog-aware score"),
                   sub="Regulator score, next 12 months, as the open backlog clears")
            + card("The five scenarios at month 12", tbl, span=12,
                   src=f'Plan method: per-case savings subtracted from today\'s days. Backlog-aware: days also fall '
                       f'by {F["queue_slope"]:.4f} days per open complaint cleared (history, months 3–24, '
                       f'r = {F["queue_r"]:.2f}). Score = {F["score"]["intercept"]:.3f} '
                       f'{minus("-")} {abs(F["score"]["slope"]):.3f} × days. Source: scenario engine and '
                       f'assumptions.yaml.')
            + "</div>")
    return page("p-reach", "Reaching 4.0", "Finding 6 · Reaching 4.0",
                "Per-case fixes alone don't reach 4.0; clearing the backlog does", lede, body)


def p_whatif(F):
    g = F["grid"]
    start = {"t": 100, "i": 50, "e": 50, "a": 0}
    levers = []
    for k, _, name, hint in LEVERS:
        btns = "".join(f'<button type="button" data-v="{v}" aria-pressed="false">{v if k == "a" else f"{v}%"}</button>'
                       for v in g["levels"][k])
        levers.append(f'<div class="lever"><div class="lv-h">{name}</div><p class="lv-x">{hint}</p>'
                      f'<div class="segs" data-k="{k}" role="group" aria-label="{name}">{btns}</div></div>')
    presets = [("Nothing", {"t": 0, "i": 0, "e": 0, "a": 0}), ("Transfers only", {"t": 100, "i": 0, "e": 0, "a": 0}),
               ("Transfers, half the rest", start), ("Everything", {"t": 100, "i": 100, "e": 100, "a": 35})]
    pre = "".join(f'<button type="button" class="preset" data-set="{esc(json.dumps(v))}">{n}</button>'
                  for n, v in presets)
    today = F["score"]["score"][-1]
    dots = "".join(
        f'<div class="dr"><span class="dr-l">{lbl}</span><div class="dr-t"><i class="dot-m {cls}" id="{i}" '
        f'style="left:{(today - 1) / 4 * 100:.1f}%"></i><b class="dr-v" id="{i}-v">{d2(today)}</b></div></div>'
        for lbl, cls, i in [("Today", "s-sq", "dt-today"), ("Plan method", "s-a", "dt-plan"),
                            ("Backlog-aware", "s-b", "dt-queue")])
    scale = (f'<div class="dots"><div class="target"><span>Target 4.0</span></div>{dots}'
             f'<div class="dr axis"><span class="dr-l"></span><div class="dr-t">'
             + "".join(f'<span style="left:{(v - 1) / 4 * 100:.0f}%">{v}</span>' for v in range(1, 6))
             + "</div></div></div>")
    res = ('<div class="verdict" id="wi-verdict" role="status"></div>' + scale
           + '<div class="kpis small">'
           + kpi("Days to close, month 12", '<span id="wi-days">–</span>', "plan method")
           + kpi("Open backlog, month 12", '<span id="wi-backlog">–</span>', "complaints still open")
           + kpi("Handling saving a year", '<span id="wi-saving">–</span>', "once fully in effect")
           + "</div>"
           + '<h4 class="mini-h">Each fix on its own, at the level picked</h4>'
           + table(["Fix", "Level", "Score, month 12<br><small>plan method</small>",
                    "Score, month 12<br><small>backlog-aware</small>"], [], cls="solo", num_from=1)
           .replace("<tbody></tbody>", '<tbody id="wi-solo"></tbody>'))
    data = {"rows": g["rows"], "start": start, "today": today,
            "names": {k: name for k, _, name, _ in LEVERS}}
    body = ('<div class="grid">'
            + card("Pick a level for each fix", "".join(levers) + f'<div class="presets"><span>Presets</span>{pre}</div>',
                   span=5, cls="levers")
            + card("Month 12, from the scenario engine", res, span=7, cls="results",
                   src=f'Every one of the {len(g["rows"])} combinations was run through the same engine as Reaching 4.0. '
                       f'Plan method: per-case savings only. Backlog-aware: days also fall as the backlog clears.')
            + "</div>"
            + f'<script type="application/json" id="whatif-data">{json.dumps(data, separators=(",", ":"))}</script>')
    return page("p-whatif", "What-if", "Try it · What-if",
                "What does each fix buy?",
                "Four levers, each at five levels (Calderfield agents: none, half or all 35 back). Pick a level for "
                "each; the result shows where the regulator score lands after 12 months, both ways.", body)


def p_method(F):
    r = F["rows"]
    data = table(["File", "Rows", "What it is"], [
        ["data/exports/complaint_360.csv", n0(r["complaint_360"]),
         "One row per complaint, joined to its intake system, meter context, staffing and unit cost"],
        ["data/exports/backlog_month.csv", n0(r["backlog_month"]), "The monthly KPI file plus the open backlog"],
        ["data/exports/region_month.csv", n0(r["region_month"]),
         "Region × month: volumes, estimated-read rate, smart-meter share, agents"],
        ["data/exports/scenarios.csv", n0(r["scenarios"]), "Five named scenarios × 12 months from the scenario engine"],
        ["data/exports/lever_grid.csv", n0(r["lever_grid"]), "Every lever combination, month-12 results"],
        ["data/exports/calibration.csv", n0(r["calibration"]), "Values the engine measured from the data pack"],
        ["data/raw/northwind_ai_pilot_2025.csv", n0(r["ai_pilot"]), "The 2025 AI assistant pilot, month by month"],
    ], num_from=1, cls="files")
    defs = [
        ("Transferred", "The complaint was passed from one system to another (transferred_between_systems = 1)."),
        ("Days to close", "Days from opened to closed; open complaints are left out of every average."),
        ("Missed the SLA", "Closed after its service-level deadline (sla_breach = 1)."),
        ("Only needed an answer", "Flagged resolvable by information only in the data pack (closed complaints)."),
        ("Billing and metering", "Categories Billing – disputed amount, Billing – estimated read and Metering – no "
                                 "read taken."),
        ("Handling cost", "Unit cost from the data pack: $121 for a transferred complaint, $68 otherwise."),
        ("Smart-meter regions", "Ashford, Calderfield, Eastmarch and Fenwick. Barrowdale and Dunmoor have none."),
    ]
    dl = "<dl class='defs'>" + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in defs) + "</dl>"
    s = F["score"]
    models = (f'<dl class="defs"><dt>Score model</dt><dd>score = {s["intercept"]:.3f} {minus("-")} '
              f'{abs(s["slope"]):.4f} × days to close. Least squares over 24 months, '
              f'{minus(f"r = {s['r']:.2f}")}. 4.0 needs {d1(s["days_for_4"])} days.</dd>'
              f'<dt>Plan method</dt><dd>Each fix removes its per-case delay from today\'s mix of complaints '
              f'(transferred or not, answer-only or not); days to close is the new weighted average.</dd>'
              f'<dt>Backlog-aware</dt><dd>Days to close also move with the open backlog: +{F["queue_slope"]:.4f} days '
              f'per open complaint (months 3–24, r = {F["queue_r"]:.2f}). Fixes free capacity (a transferred complaint '
              f'costs about 1.8× the effort), the backlog clears, days fall.</dd>'
              f'<dt>Caveat</dt><dd>Both are models. The plan method is the cautious headline; the backlog-aware view '
              f'depends on the backlog link holding.</dd></dl>')
    notes = ('<ul class="notes"><li>Findings 1–5 use only the Northwind data pack. The synthetic meter reads and '
             'bills used by the OneCase app appear nowhere in this report.</li>'
             '<li>Projections (Reaching 4.0, What-if, the last summary card) come from the scenario engine and '
             '<code>assumptions.yaml</code>.</li>'
             '<li>Payback is not shown: build and run costs are still TBD in <code>assumptions.yaml</code>.</li>'
             '<li>Rebuild this file with <code>python run.py report</code> (it also rebuilds with '
             '<code>python run.py data</code>). The numbers are checked by <code>tests/test_report.py</code>.</li></ul>')
    body = ('<div class="grid">'
            + card("Data used, as loaded", data, span=7)
            + card("Definitions", dl, span=5)
            + card("Models", models, span=7)
            + card("Notes", notes, span=5)
            + "</div>")
    return page("p-method", "Method", "Method and data", "Where every number comes from",
                "The files the report reads, the definitions behind each measure, and the two models.", body)


# --------------------------------------------------------------------------- page shell
CSS = r"""
:root {
  color-scheme: light;
  --paper: #e9eef1; --panel: #ffffff; --ink: #0d1b26; --ink-2: #3f4d59; --muted: #6f7c87;
  --rule: #d2dae0; --grid: #e6ebee; --axis: #b9c3ca; --bar: #0d1b26; --brand: #ffcb2e; --hover: rgba(13,27,38,.055);
  --c-a: #2a78d6; --c-b: #e0612b; --c-c: #6b5bd6; --c-good: #138a61; --c-pink: #d0508c; --c-sq: #7d8790;
  --c-m: #84919c; --c-ctx: #b3bec6;
  --good: #0b7a3f; --good-wash: #e7f5ec; --bad: #b8431b; --hl: #fff4ea; --focus: #1543c4;
  --display: "Bahnschrift", "DIN Alternate", "Barlow", "Arial Narrow", system-ui, sans-serif;
  --body: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --paper: #0a1424; --panel: #101d31; --ink: #eef3f8; --ink-2: #b4c3d3; --muted: #8397ad;
  --rule: #22385a; --grid: #1a2d4a; --axis: #35507a; --bar: #060d18; --hover: rgba(255,255,255,.06);
  --c-a: #5b9cf0; --c-b: #f08a4f; --c-c: #a596ff; --c-good: #34c38f; --c-pink: #f08fbd; --c-sq: #98a4b3;
  --c-m: #6d819b; --c-ctx: #3f5679;
  --good: #5fd39a; --good-wash: #0f2d22; --bad: #ff9a6b; --hl: #1d2a3f; --focus: #8fb6ff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --paper: #0a1424; --panel: #101d31; --ink: #eef3f8; --ink-2: #b4c3d3; --muted: #8397ad;
    --rule: #22385a; --grid: #1a2d4a; --axis: #35507a; --bar: #060d18; --hover: rgba(255,255,255,.06);
    --c-a: #5b9cf0; --c-b: #f08a4f; --c-c: #a596ff; --c-good: #34c38f; --c-pink: #f08fbd; --c-sq: #98a4b3;
    --c-m: #6d819b; --c-ctx: #3f5679;
    --good: #5fd39a; --good-wash: #0f2d22; --bad: #ff9a6b; --hl: #1d2a3f; --focus: #8fb6ff;
  }
}
* { box-sizing: border-box; }
html { font-size: 17px; }
body { margin: 0; background: var(--paper); color: var(--ink); font-family: var(--body); line-height: 1.45; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
button { font: inherit; color: inherit; }
code { font-family: "Cascadia Mono", Consolas, monospace; font-size: .88em; background: var(--grid); padding: 1px 5px; border-radius: 4px; }

/* top bar */
.top { position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 18px; padding: 10px 24px;
  background: var(--bar); color: #fff; }
.brand { font-family: var(--display); font-weight: 600; font-size: 1.3rem; white-space: nowrap; }
.brand b { color: var(--brand); font-weight: 700; }
.brand small { font-weight: 400; font-size: .8rem; opacity: .7; margin-left: 8px; }
.tabs { display: flex; gap: 2px; overflow-x: auto; scrollbar-width: none; min-width: 0; flex: 1; }
.tabs::-webkit-scrollbar { display: none; }
.tabs a { color: #c9d4dc; text-decoration: none; padding: 7px 11px; border-radius: 6px; font-size: .86rem; white-space: nowrap; }
.tabs a:hover { background: rgba(255,255,255,.1); color: #fff; }
.tabs a[aria-selected="true"] { background: #fff; color: #0d1b26; font-weight: 600; }
.tabs a i { font-style: normal; opacity: .55; margin-right: 5px; font-family: var(--display); }
.tb { background: transparent; border: 1px solid rgba(255,255,255,.35); color: #fff; border-radius: 6px;
  padding: 6px 12px; cursor: pointer; font-size: .86rem; white-space: nowrap; }
.tb:hover { background: rgba(255,255,255,.1); }

main { max-width: 1480px; margin: 0 auto; padding: 22px 24px 40px; }
.p-head { margin: 4px 0 18px; }
.eyebrow { font-family: var(--display); letter-spacing: .08em; text-transform: uppercase; font-size: .78rem;
  color: var(--muted); margin: 0 0 6px; font-weight: 600; }
h2 { font-family: var(--display); font-size: clamp(1.55rem, 2.5vw, 2.35rem); line-height: 1.12; margin: 0 0 10px;
  font-weight: 600; max-width: 30em; text-wrap: balance; }
.lede { font-size: 1.04rem; color: var(--ink-2); margin: 0; max-width: 78ch; }
.sec { font-family: var(--display); font-size: 1.05rem; letter-spacing: .06em; text-transform: uppercase;
  color: var(--muted); margin: 26px 0 10px; font-weight: 600; }

.grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 16px; }
.span-5 { grid-column: span 5; } .span-6 { grid-column: span 6; } .span-7 { grid-column: span 7; }
.span-12 { grid-column: span 12; }
.card { margin: 0; background: var(--panel); border: 1px solid var(--rule); border-radius: 10px;
  padding: 16px 18px 14px; display: flex; flex-direction: column; min-width: 0; }
.card h3 { font-size: 1.04rem; font-weight: 650; margin: 0; line-height: 1.3; text-wrap: balance; }
.card .sub { margin: 3px 0 0; color: var(--muted); font-size: .84rem; }
.viz { margin-top: 12px; flex: 1; min-width: 0; }
.src { margin: 10px 0 0; font-size: .76rem; color: var(--muted); }

.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 12px; }
.kpi { background: var(--panel); border: 1px solid var(--rule); border-radius: 10px; padding: 13px 16px; }
.k-l { font-size: .82rem; color: var(--ink-2); line-height: 1.3; }
.k-v { font-family: var(--display); font-size: 2.15rem; font-weight: 600; line-height: 1.1; margin-top: 5px;
  font-variant-numeric: tabular-nums; }
.k-s { font-size: .78rem; color: var(--muted); margin-top: 3px; }
.kpi.bad { box-shadow: inset 4px 0 0 var(--c-b); }
.kpi.good { box-shadow: inset 4px 0 0 var(--c-good); }
.kstack { display: grid; gap: 10px; }
.kstack .kpi, .kpis.small .kpi { background: transparent; }
.kpis.small .k-v { font-size: 1.7rem; }

/* summary findings */
.finds { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.find { display: grid; grid-template-columns: auto 1fr; column-gap: 12px; row-gap: 4px; text-decoration: none; color: inherit;
  background: var(--panel); border: 1px solid var(--rule); border-radius: 10px; padding: 16px 18px; transition: border-color .15s, transform .15s; }
.find:hover { border-color: var(--c-a); transform: translateY(-2px); }
.f-n { grid-row: span 4; font-family: var(--display); font-weight: 700; font-size: 1.1rem; color: var(--panel);
  background: var(--ink); width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; }
.f-t { font-weight: 650; }
.f-v { font-family: var(--display); font-size: 1.75rem; font-weight: 600; line-height: 1.15; font-variant-numeric: tabular-nums; }
.f-x { color: var(--ink-2); font-size: .9rem; }
.f-go { color: var(--c-a); font-size: .84rem; font-weight: 600; margin-top: 4px; }
.howto { color: var(--muted); font-size: .84rem; margin: 18px 0 0; }

/* charts */
.chart { display: block; width: 100%; height: auto; overflow: visible; font-family: var(--body); }
.chart text { font-size: 12.5px; }
.chart .ax { fill: var(--muted); font-variant-numeric: tabular-nums; }
.chart .at { fill: var(--muted); }
.chart .gl { stroke: var(--grid); stroke-width: 1; }
.chart .bl { stroke: var(--axis); stroke-width: 1.2; }
.chart .ref, .chart .fit { stroke: var(--ink); stroke-width: 1.4; stroke-dasharray: 5 4; opacity: .65; }
.chart .refl { fill: var(--ink-2); font-weight: 600; }
.chart .ln { fill: none; stroke: var(--c); stroke-width: 2.6; stroke-linejoin: round; stroke-linecap: round; }
.chart .ln.thin { stroke-width: 1.6; }
.chart .ln.bold { stroke-width: 3.8; }
.chart .ln, .chart .dot { pointer-events: none; }
.chart .dot { fill: var(--c); stroke: var(--panel); stroke-width: 2; }
.chart .pt { fill: var(--c); stroke: var(--panel); stroke-width: 1.5; cursor: default; }
.chart .pt:hover { stroke: var(--ink); stroke-width: 2; }
.chart .bar { fill: var(--c); }
.chart .lead { stroke: var(--c); stroke-width: 1.2; }
.chart .dl { fill: var(--ink-2); font-size: 13px; cursor: default; }
.chart .dl .v { fill: var(--ink); font-weight: 700; font-variant-numeric: tabular-nums; }
.chart .vl { fill: var(--ink); font-family: var(--display); font-size: 13.5px; font-weight: 600; font-variant-numeric: tabular-nums; }
.chart .cl { fill: var(--ink-2); font-size: 13px; }
.chart .hov { fill: transparent; }
.chart .hov:hover, .chart [data-tip]:hover > .hov { fill: var(--hover); }
.chart g[data-s] { transition: opacity .15s; }
.chart.focus g[data-s]:not(.on) { opacity: .16; }
.s-a { --c: var(--c-a); } .s-b { --c: var(--c-b); } .s-c { --c: var(--c-c); } .s-good { --c: var(--c-good); }
.s-pink { --c: var(--c-pink); } .s-sq { --c: var(--c-sq); } .s-m { --c: var(--c-m); } .s-ctx { --c: var(--c-ctx); }
.multis { display: grid; grid-template-columns: 1fr 1fr; gap: 18px 28px; align-items: start; }
.mult h4 { margin: 0 0 4px; font-size: .84rem; color: var(--ink-2); font-weight: 600; }
.note { margin: 14px 0 0; padding: 12px 14px; border-left: 4px solid var(--c-b); background: var(--hl); border-radius: 0 8px 8px 0;
  font-size: 1.05rem; font-weight: 600; }
.note cite { display: block; font-style: normal; font-weight: 400; font-size: .78rem; color: var(--muted); margin-top: 4px; }

/* tooltip */
.tip { position: fixed; left: 0; top: 0; z-index: 50; pointer-events: none; background: var(--ink); color: var(--panel);
  font-size: .8rem; padding: 8px 11px; border-radius: 7px; box-shadow: 0 6px 22px rgba(0,0,0,.25); opacity: 0;
  transition: opacity .08s; max-width: 300px; }
.tip.on { opacity: 1; }
.tip strong { display: block; margin-bottom: 4px; font-size: .84rem; }
.tip .tr { display: grid; grid-template-columns: auto auto; gap: 2px 14px; }
.tip .tr b { text-align: right; font-variant-numeric: tabular-nums; }
.tip .sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; background: var(--c); margin-right: 6px; vertical-align: -1px; }

/* tables */
.tbl { width: 100%; border-collapse: collapse; font-size: .92rem; }
.tbl th { text-align: left; font-weight: 600; color: var(--ink-2); font-size: .8rem; padding: 6px 10px; border-bottom: 2px solid var(--rule);
  vertical-align: bottom; line-height: 1.25; }
.tbl th small, .tbl td small { display: block; font-weight: 400; color: var(--muted); font-size: .78rem; }
.tbl td { padding: 9px 10px; border-bottom: 1px solid var(--rule); font-variant-numeric: tabular-nums; }
.tbl .n { text-align: right; }
.tbl tr.hl td { background: var(--hl); }
.tbl tr.hl td:first-child { box-shadow: inset 4px 0 0 var(--c-b); }
.tbl.cmp td { font-size: 1.02rem; padding: 12px 10px; }
.tbl.cmp td:nth-child(2) { font-family: var(--display); font-weight: 600; font-size: 1.25rem; }
.tbl.cmp td:nth-child(3) { font-family: var(--display); font-size: 1.25rem; }
.tbl.cmp td:nth-child(4) { color: var(--bad); font-weight: 600; }
.tbl.scen td:nth-child(n+2) { font-family: var(--display); font-size: 1.1rem; }
.tbl .ok { background: var(--good-wash); color: var(--good); font-weight: 700; padding: 2px 7px; border-radius: 4px; }
.tbl.files td:first-child { font-family: "Cascadia Mono", Consolas, monospace; font-size: .82rem; }
.tbl.files td:last-child, .tbl.files th:last-child { text-align: left; }
.defs { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 8px 16px; font-size: .9rem; }
.defs dt { font-weight: 650; }
.defs dd { margin: 0; color: var(--ink-2); }
.notes { margin: 0; padding-left: 18px; font-size: .9rem; color: var(--ink-2); display: grid; gap: 8px; }

/* what-if */
.lever { padding: 10px 0 12px; border-bottom: 1px solid var(--rule); }
.lv-h { font-weight: 650; }
.lv-x { margin: 1px 0 8px; font-size: .82rem; color: var(--muted); }
.segs { display: flex; gap: 4px; background: var(--grid); padding: 3px; border-radius: 8px; }
.segs button { flex: 1; border: 0; background: transparent; padding: 7px 4px; border-radius: 6px; cursor: pointer;
  font-family: var(--display); font-weight: 600; font-size: .98rem; color: var(--ink-2); }
.segs button:hover { background: var(--hover); }
.segs button[aria-pressed="true"] { background: var(--ink); color: var(--panel); }
.mini-h { margin: 20px 0 4px; font-size: .9rem; font-weight: 650; }
.tbl.solo td { padding: 7px 10px; }
.tbl.solo td:nth-child(n+3) { font-family: var(--display); font-size: 1.05rem; }
.presets { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 14px; font-size: .84rem; color: var(--muted); }
.presets span { margin-right: 4px; }
.preset { border: 1px solid var(--rule); background: transparent; border-radius: 999px; padding: 4px 12px; cursor: pointer; font-size: .84rem; }
.preset:hover { border-color: var(--c-a); }
.verdict { font-family: var(--display); font-size: 1.5rem; font-weight: 600; padding: 12px 16px; border-radius: 8px;
  background: var(--hl); border-left: 5px solid var(--c-b); }
.verdict.yes { background: var(--good-wash); border-color: var(--c-good); color: var(--good); }
.verdict.maybe { border-color: var(--c-a); }
.verdict small { display: block; font-family: var(--body); font-weight: 400; font-size: .86rem; color: var(--ink-2); margin-top: 2px; }
.dots { position: relative; margin: 22px 0 14px; }
.dr { display: grid; grid-template-columns: 120px 1fr; align-items: center; height: 44px; }
.dr-l { font-size: .9rem; color: var(--ink-2); }
.dr-t { position: relative; height: 100%; border-bottom: 1px solid var(--grid); margin-right: 50px; }
.dot-m { position: absolute; top: 50%; width: 16px; height: 16px; margin: -8px 0 0 -8px; border-radius: 50%; background: var(--c);
  border: 2px solid var(--panel); transition: left .35s ease; }
.dr-v { position: absolute; top: 50%; transform: translate(14px, -50%); font-family: var(--display); font-size: 1.25rem;
  font-variant-numeric: tabular-nums; transition: left .35s ease; white-space: nowrap; }
.dr.axis { height: 24px; }
.dr.axis .dr-t { border: 0; }
.dr.axis .dr-t span { position: absolute; transform: translateX(-50%); font-size: .8rem; color: var(--muted); }
.target { position: absolute; top: -18px; bottom: 22px; left: 75%; margin-left: 0; border-left: 2px dashed var(--ink); opacity: .6;
  pointer-events: none; }
.dots .target { left: calc(120px + (100% - 170px) * .75); }
.target span { position: absolute; top: -4px; left: 6px; font-size: .78rem; font-weight: 600; white-space: nowrap; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }

/* pager */
.pager { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-top: 28px; padding-top: 14px;
  border-top: 1px solid var(--rule); font-size: .9rem; }
.pager a { color: var(--c-a); text-decoration: none; font-weight: 600; }
.pager a:hover { text-decoration: underline; }
.pager span { color: var(--muted); }
footer { max-width: 1480px; margin: 0 auto; padding: 0 24px 30px; color: var(--muted); font-size: .78rem; }

.js .page { display: none; }
.js .page.on { display: block; }
.page + .page { margin-top: 48px; }
.js .page + .page { margin-top: 0; }

@media (max-width: 1100px) {
  .grid > * { grid-column: 1 / -1; }
  .finds { grid-template-columns: 1fr 1fr; }
  .brand small { display: none; }
}
@media (max-width: 640px) {
  html { font-size: 16px; }
  main { padding: 16px 16px 30px; }
  .top { padding: 8px 16px; gap: 10px; flex-wrap: wrap; }
  .tabs { order: 3; flex-basis: 100%; }
  .viz { overflow-x: auto; }
  .viz .chart { min-width: 520px; }
  .multis, .finds { grid-template-columns: 1fr; }
  .dr { grid-template-columns: 96px 1fr; }
  .dots .target { left: calc(96px + (100% - 146px) * .75); }
  #print { display: none; }
}
@media print {
  :root { color-scheme: light; }
  .top, .pager, .howto, .presets, #print, #theme { display: none !important; }
  body { background: #fff; }
  .js .page { display: block !important; break-before: page; }
  .card, .kpi, .find { break-inside: avoid; }
  main { max-width: none; padding: 0; }
}
"""

JS = r"""
(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;
  root.classList.add("js");

  // pages: tabs, hash links, arrow keys
  const pages = $$(".page"), tabs = $$(".tabs a");
  function show(id) {
    const p = pages.find(x => x.id === id) || pages[0];
    pages.forEach(x => x.classList.toggle("on", x === p));
    tabs.forEach(a => a.setAttribute("aria-selected", String(a.getAttribute("href") === "#" + p.id)));
    const cur = tabs.find(a => a.getAttribute("aria-selected") === "true");
    if (cur) cur.scrollIntoView({ block: "nearest", inline: "nearest" });
    document.title = p.dataset.title + " · Northwind diagnosis report";
    window.scrollTo(0, 0);
  }
  addEventListener("hashchange", () => show(location.hash.slice(1)));
  show(location.hash.slice(1));
  addEventListener("keydown", e => {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.target.closest && e.target.closest("input, textarea, select, .segs")) return;
    const i = pages.findIndex(p => p.classList.contains("on"));
    const j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : -1;
    if (j >= 0 && j < pages.length) { e.preventDefault(); location.hash = pages[j].id; }
  });

  // light / dark
  const tbtn = $("#theme");
  const mode = () => root.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const label = () => { tbtn.textContent = mode() === "dark" ? "Light" : "Dark"; };
  tbtn.addEventListener("click", () => {
    root.dataset.theme = mode() === "dark" ? "light" : "dark";
    try { localStorage.setItem("nw-report-theme", root.dataset.theme); } catch (e) {}
    label();
  });
  label();
  $("#print").addEventListener("click", () => window.print());

  // tooltip for anything with data-tip
  const tip = document.createElement("div");
  tip.className = "tip"; tip.setAttribute("role", "tooltip");
  document.body.append(tip);
  let on = null;
  document.addEventListener("pointermove", e => {
    const t = e.target.closest ? e.target.closest("[data-tip]") : null;
    if (t !== on) { on = t; if (t) { tip.innerHTML = t.dataset.tip; tip.classList.add("on"); } else tip.classList.remove("on"); }
    if (!t) return;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + 14, y = e.clientY + 14;
    if (x + w > innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > innerHeight - 8) y = e.clientY - h - 14;
    tip.style.transform = `translate(${x}px, ${y}px)`;
  });
  document.addEventListener("pointerleave", () => { on = null; tip.classList.remove("on"); });

  // multi-line charts: point at a line's label to bring that line forward
  document.addEventListener("pointerover", e => {
    const g = e.target.closest ? e.target.closest("svg.multi g[data-s]") : null;
    const svg = g && g.ownerSVGElement;
    $$("svg.focus").forEach(s => { if (s !== svg) s.classList.remove("focus"); });
    if (!g) return;
    svg.classList.add("focus");
    $$("g[data-s]", svg).forEach(x => x.classList.toggle("on", x.dataset.s === g.dataset.s));
  });

  // what-if levers
  const dataEl = $("#whatif-data");
  if (!dataEl) return;
  const W = JSON.parse(dataEl.textContent), st = Object.assign({}, W.start);
  const pos = v => ((Math.min(5, Math.max(1, v)) - 1) / 4 * 100).toFixed(1) + "%";
  const place = (id, v) => { $("#" + id).style.left = pos(v); const t = $("#" + id + "-v"); t.style.left = pos(v); t.textContent = v.toFixed(2); };
  function update() {
    $$(".segs").forEach(g => $$("button", g).forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.v === st[g.dataset.k]))));
    const r = W.rows[[st.t, st.i, st.e, st.a].join("|")];
    if (!r) return;
    const [plan, queue, days, backlog, saving] = r;
    place("dt-today", W.today); place("dt-plan", plan); place("dt-queue", queue);
    $("#wi-days").textContent = days.toFixed(1);
    $("#wi-backlog").textContent = Math.round(backlog).toLocaleString("en-US");
    $("#wi-saving").textContent = "$" + Math.round(saving).toLocaleString("en-US");
    const solo = $("#wi-solo"), keys = ["t", "i", "e", "a"];
    solo.innerHTML = keys.map(k => {
      const one = W.rows[keys.map(j => (j === k ? st[j] : 0)).join("|")];
      const lvl = k === "a" ? st[k] + " agents" : st[k] + "%";
      const cell = x => '<td class="n"><span class="' + (x >= 4 ? "ok" : "") + '">' + x.toFixed(2) + "</span></td>";
      return "<tr><td>" + W.names[k] + '</td><td class="n">' + lvl + "</td>" + cell(one[0]) + cell(one[1]) + "</tr>";
    }).join("");
    const v = $("#wi-verdict");
    if (plan >= 4) { v.className = "verdict yes"; v.innerHTML = "4.0 reached<small>even on the cautious plan method</small>"; }
    else if (queue >= 4) { v.className = "verdict maybe"; v.innerHTML = "4.0 only if the backlog clears<small>plan method stops at " + plan.toFixed(2) + "</small>"; }
    else { v.className = "verdict"; v.innerHTML = "4.0 not reached<small>best of the two views: " + Math.max(plan, queue).toFixed(2) + "</small>"; }
  }
  $$(".segs button").forEach(b => b.addEventListener("click", () => { st[b.closest(".segs").dataset.k] = +b.dataset.v; update(); }));
  $$(".preset").forEach(b => b.addEventListener("click", () => { Object.assign(st, JSON.parse(b.dataset.set)); update(); }));
  update();
})();
"""

HEAD_JS = ('try{var t=localStorage.getItem("nw-report-theme");if(t)document.documentElement.dataset.theme=t}'
           'catch(e){}')


def render(F: dict) -> str:
    pages = [(p_summary, "Summary"), (p_score, "Score"), (p_transfers, "Transfers"), (p_billing, "Billing"),
             (p_answers, "Answers & AI"), (p_calderfield, "Calderfield"), (p_reach, "Reaching 4.0"),
             (p_whatif, "What-if"), (p_method, "Method")]
    html_pages = [fn(F) for fn, _ in pages]
    ids = [h.split('id="', 1)[1].split('"', 1)[0] for h in html_pages]
    n = len(pages)
    out = []
    for i, h in enumerate(html_pages):
        prev = f'<a href="#{ids[i - 1]}">← {pages[i - 1][1]}</a>' if i else "<span></span>"
        nxt = f'<a href="#{ids[i + 1]}">{pages[i + 1][1]} →</a>' if i < n - 1 else "<span></span>"
        out.append(h.replace("</section>", f'<nav class="pager">{prev}<span>{i + 1} / {n}</span>{nxt}</nav></section>'))
    tabs = "".join(f'<a href="#{pid}" role="tab" aria-selected="false">{name}</a>'
                   for pid, (_, name) in zip(ids, pages))
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Northwind diagnosis report</title>
<meta name="description" content="Why Northwind's complaint score fell, and what reaches 4.0: nine pages built from the data pack.">
<script>{HEAD_JS}</script>
<style>{CSS}</style>
</head>
<body>
<header class="top">
  <div class="brand">NORTHWIND <b>OneCase</b><small>Diagnosis report</small></div>
  <nav class="tabs" role="tablist" aria-label="Report pages">{tabs}</nav>
  <button class="tb" id="theme" type="button">Dark</button>
  <button class="tb" id="print" type="button">Print / PDF</button>
</header>
<main>
{"".join(out)}
</main>
<footer>Generated {stamp} by <code>python run.py report</code> from data/exports and the data pack's AI pilot file.
Works offline: no fonts, scripts or images load from anywhere else.</footer>
<script>{JS}</script>
</body>
</html>
"""


def build(path=OUT) -> dict:
    F = facts()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(F), encoding="utf-8")
    return F


def main() -> int:
    build()
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
