"""Phase 2: scenario and backlog engine.

Answers: is a 4.0 regulator score reachable in 12 months, which fixes get closest,
and what are they worth?

    python -m src.scenario                      # the 5 named scenarios + exports
    python -m src.scenario --transfers 1 --info 0.5
    python -m src.scenario --calibration        # every data-derived number, with source

Method (all inputs from assumptions.yaml or derived from data/raw):

1. Days to close, STATIC view (the plan's method, the headline by default).
   Closed complaints are split into four cells: information-only (yes/no) x transferred (yes/no).
   Each cell has a historical share and average days. The levers change cell days:
     - transfers_removed t:   a transferred case takes the days of its non-transferred twin
     - info_only_first_contact f: an information-only case closes in `info_only_days_if_first_contact`
   Info-only cases that were ALSO transferred sit in one cell (d11). First contact is applied
   after the transfer fix, so a case is never credited twice: its days go to 1 whatever t is.
   saved days = historical mix average - lever mix average; avg days = baseline - saved days.

2. Backlog path, month by month for 12 months.
   intake falls with estimated_read_reduction (estimate-read and no-read categories only);
   information-only cases answered at first contact close the same month and never queue;
   queue capacity is measured in effort: a transferred case costs 121/68 = 1.78 units, so
   removing transfers frees capacity; restored agents add capacity pro rata to headcount.
   All levers ramp linearly to full effect over `months_to_full_effect`.

3. QUEUE view of days (cross-check). Historically days to close rises ~0.017 days for every
   extra open case (non-transferred cases only, so it does not overlap the transfer effect).
   queue days = static days - slope x (baseline backlog - backlog this month), floored.

4. Score = intercept + slope x days, clamped to [floor, cap]. Target met if score >= target.
"""
from __future__ import annotations

import argparse
import itertools
import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from .config import EXPORTS, connect, load_assumptions, val
from .model360 import ESTIMATE_CATEGORIES

LEVERS = ["transfers_removed", "info_only_first_contact", "estimated_read_reduction",
          "calderfield_agents_restored"]
DAYS_PER_MONTH = 30.4


# ---------------------------------------------------------------------------
# Calibration: numbers derived from the data pack (never typed in by hand)
# ---------------------------------------------------------------------------
@dataclass
class Calibration:
    cells: dict            # (info, transferred) -> {"share", "days", "n"}
    hist_mean_days: float
    transfer_share: float  # of all complaints (intake mix)
    info_share: float      # of closed complaints with a known flag
    estimate_share: float  # estimate-read + no-read categories, of all complaints
    correction_rate_estimate: float
    correction_rate_other: float
    queue_slope: float     # days per open case (non-transferred cases)
    queue_fit_r: float
    agents_now: float
    sources: dict = field(default_factory=dict)

    def rows(self) -> list[dict]:
        out = []
        for (i, t), c in sorted(self.cells.items()):
            label = f"info_only={i}, transferred={t}"
            out.append({"name": f"cell days [{label}]", "value": round(c["days"], 3),
                        "source": self.sources["cells"]})
            out.append({"name": f"cell share [{label}]", "value": round(c["share"], 4),
                        "source": self.sources["cells"]})
        for k in ["hist_mean_days", "transfer_share", "info_share", "estimate_share",
                  "correction_rate_estimate", "correction_rate_other", "queue_slope",
                  "queue_fit_r", "agents_now"]:
            out.append({"name": k, "value": round(getattr(self, k), 5), "source": self.sources[k]})
        return out


def calibrate(assumptions: dict, con=None) -> Calibration:
    own = con is None
    con = con or connect()
    c = pd.read_sql("SELECT * FROM complaints", con)
    backlog = pd.read_sql("SELECT * FROM backlog_month ORDER BY month", con)
    staff = pd.read_sql("SELECT month, agent_fte FROM staffing", con)
    if own:
        con.close()

    window = int(val(assumptions["calibration"]["window_months"]))
    months = sorted(c["month_closed"].dropna().unique())[-window:]
    closed = c[c["month_closed"].isin(months)]
    g = closed.groupby(["resolvable_by_information_only", "transferred_between_systems"])["days_to_close"]
    stats = g.agg(["mean", "size"])
    total = stats["size"].sum()
    cells = {(int(i), int(t)): {"share": n / total, "days": float(d), "n": int(n)}
             for (i, t), (d, n) in stats.iterrows()}
    hist_mean = sum(v["share"] * v["days"] for v in cells.values())

    all_closed = c[c["month_closed"].notna()]
    corr = all_closed["resolution_action"] == "Bill corrected and re-issued"
    is_est = all_closed["category"].isin(ESTIMATE_CATEGORIES)

    skip = int(val(assumptions["queue_model"]["fit_skip_months"]))
    fit = backlog.iloc[skip:]
    slope, _ = np.polyfit(fit["backlog_avg"], fit["avg_days_not_transferred"], 1)
    r = float(np.corrcoef(fit["backlog_avg"], fit["avg_days_not_transferred"])[0, 1])

    last = staff["month"].max()
    src_c = "northwind_complaints.csv"
    return Calibration(
        cells=cells,
        hist_mean_days=hist_mean,
        transfer_share=float(c["transferred_between_systems"].mean()),
        info_share=float(all_closed["resolvable_by_information_only"].mean()),
        estimate_share=float(c["category"].isin(ESTIMATE_CATEGORIES).mean()),
        correction_rate_estimate=float(corr[is_est].mean()),
        correction_rate_other=float(corr[~is_est].mean()),
        queue_slope=float(slope),
        queue_fit_r=r,
        agents_now=float(staff.loc[staff["month"] == last, "agent_fte"].sum()),
        sources={
            "cells": f"{src_c}, closed in last {window} months ({months[0]}..{months[-1]})",
            "hist_mean_days": f"{src_c}, weighted mean of the four cells",
            "transfer_share": f"{src_c}, all 25,416 complaints",
            "info_share": f"{src_c}, closed complaints (flag is blank on open ones)",
            "estimate_share": f"{src_c}, categories {', '.join(ESTIMATE_CATEGORIES)}",
            "correction_rate_estimate": f"{src_c}, 'Bill corrected and re-issued' share, estimate categories",
            "correction_rate_other": f"{src_c}, same, all other categories",
            "queue_slope": f"backlog_month (complaints + KPI files), OLS of non-transferred days on "
                           f"open backlog, months {skip + 1}-24",
            "queue_fit_r": "same fit",
            "agents_now": f"northwind_contact_centre_staffing.csv, sum of agent_fte in {last}",
        },
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def clean_levers(levers: dict | None, assumptions: dict) -> dict:
    """Fill defaults and clamp every lever to its declared range."""
    spec = assumptions["levers"]
    out = {}
    for k in LEVERS:
        v = (levers or {}).get(k)
        v = spec[k]["default"] if v is None else float(v)
        out[k] = min(max(v, spec[k]["min"]), spec[k]["max"])
    return out


def mix_days(cal: Calibration, t: float, f: float, fc_days: float) -> float:
    """Average days on the historical mix with levers t (transfers) and f (first contact).

    This is where the overlap is handled: cell (1,1) gets the transfer fix first, then
    first contact replaces whatever is left, so its saving is never counted twice.
    """
    d = {k: v["days"] for k, v in cal.cells.items()}
    s = {k: v["share"] for k, v in cal.cells.items()}
    d01 = d[(0, 1)] - t * (d[(0, 1)] - d[(0, 0)])
    d11_after_transfer = d[(1, 1)] - t * (d[(1, 1)] - d[(1, 0)])
    d10 = f * fc_days + (1 - f) * d[(1, 0)]
    d11 = f * fc_days + (1 - f) * d11_after_transfer
    return s[(0, 0)] * d[(0, 0)] + s[(0, 1)] * d01 + s[(1, 0)] * d10 + s[(1, 1)] * d11


def score_of(days: float, a: dict) -> float:
    sm = a["score_model"]
    raw = val(sm["intercept"]) + val(sm["slope_per_day"]) * days
    return min(max(raw, val(sm["floor"])), val(sm["cap"]))


def _cost(a: dict, key: str):
    """A team cost line, or None while it is still TBD."""
    v = val(a["team_estimates"].get(key)) if key in a["team_estimates"] else val(a["unit_costs"][key])
    return None if v in (None, "TBD") else float(v)


def run(levers: dict | None = None, assumptions: dict | None = None, cal: Calibration | None = None,
        months: int = 12, build_cost_keys=(), run_cost_keys=()) -> dict:
    a = assumptions or load_assumptions()
    cal = cal or get_calibration()
    lv = clean_levers(levers, a)
    b, te, uc = a["baseline"], a["team_estimates"], a["unit_costs"]

    base_days = val(b["avg_days_to_close"])
    b0 = val(b["open_backlog"])
    opened0 = val(b["monthly_opened"])
    closed0 = val(b["monthly_closed"])
    ramp_months = val(te["months_to_full_effect"])
    fc_days = val(te["info_only_days_if_first_contact"])
    fc_cost = val(te["first_contact_unit_cost"])
    c_avg, c_tr = val(uc["complaint_avg"]), val(uc["complaint_transferred"])
    k = c_tr / c_avg  # effort of a transferred case relative to an average one (1.78)
    effort0 = 1 + cal.transfer_share * (k - 1)
    capacity_effort0 = closed0 * effort0
    floor_days = val(a["queue_model"]["floor_days"])
    queue_headline = bool(val(a["queue_model"]["headline"]))
    additive = val(a["calibration"]["saving_method"]) == "additive"
    y0, m0 = map(int, val(b["month"]).split("-"))

    rows, backlog = [], float(b0)
    for m in range(1, months + 1):
        r = min(1.0, m / ramp_months) if ramp_months else 1.0
        t, f = lv["transfers_removed"] * r, lv["info_only_first_contact"] * r
        e, agents = lv["estimated_read_reduction"] * r, lv["calderfield_agents_restored"] * r

        # --- days, static view
        mix = mix_days(cal, t, f, fc_days)
        saved = cal.hist_mean_days - mix
        days_static = base_days - saved if additive else base_days * mix / cal.hist_mean_days
        days_static = max(days_static, fc_days)

        # --- backlog path
        intake = opened0 * (1 - cal.estimate_share * e)
        first_contact = intake * cal.info_share * f
        queue_in = intake - first_contact
        ts = cal.transfer_share * (1 - t)
        effort = 1 + ts * (k - 1)
        capacity = capacity_effort0 * (1 + agents / cal.agents_now) / effort
        working_stock = queue_in * floor_days / DAYS_PER_MONTH  # the queue can't empty below this
        closures = min(capacity, max(0.0, backlog + queue_in - working_stock))
        start = backlog
        backlog = start + queue_in - closures

        # --- days, queue view
        days_queue = days_static - cal.queue_slope * (b0 - (start + backlog) / 2)
        days_queue = max(days_queue, floor_days if days_static >= floor_days else days_static)

        # --- handling cost this month (run rate: every complaint that arrives gets handled once)
        est_intake = opened0 * cal.estimate_share * (1 - e)
        other_intake = opened0 * (1 - cal.estimate_share)
        corrections = est_intake * cal.correction_rate_estimate + other_intake * cal.correction_rate_other
        handling = (queue_in * (ts * c_tr + (1 - ts) * c_avg) + first_contact * fc_cost
                    + corrections * val(uc["bill_correction"]))

        days = days_queue if queue_headline else days_static
        yy, mm = divmod(m0 - 1 + m, 12)
        rows.append({
            "month_index": m, "month": f"{y0 + yy}-{mm + 1:02d}", "ramp": round(r, 3),
            "intake": intake, "first_contact_closed": first_contact, "queue_intake": queue_in,
            "capacity": capacity, "closures": closures, "closed_total": closures + first_contact,
            "backlog": backlog, "working_stock": working_stock,
            "avg_days_static": days_static, "score_static": score_of(days_static, a),
            "avg_days_queue": days_queue, "score_queue": score_of(days_queue, a),
            "avg_days": days, "score": score_of(days, a),
            "handling_cost": handling,
            "agents_cost": agents * val(uc["agent_fte_year"]) / 12,
        })
    df = pd.DataFrame(rows)
    target = val(a["score_model"]["target"])
    df["target_met"] = df["score"] >= target

    status_quo_cost = _status_quo_monthly_cost(a, cal, opened0, c_avg, c_tr, fc_cost)
    df["handling_saving"] = status_quo_cost - df["handling_cost"]

    return {
        "levers": lv,
        "months": df,
        "summary": _summarise(df, a, cal, build_cost_keys, run_cost_keys, status_quo_cost),
    }


def _status_quo_monthly_cost(a, cal, opened0, c_avg, c_tr, fc_cost) -> float:
    ts = cal.transfer_share
    corrections = opened0 * (cal.estimate_share * cal.correction_rate_estimate
                             + (1 - cal.estimate_share) * cal.correction_rate_other)
    return (opened0 * (ts * c_tr + (1 - ts) * c_avg)
            + corrections * val(a["unit_costs"]["bill_correction"]))


def _first_month(df: pd.DataFrame, col: str, target: float):
    hit = df.loc[df[col] >= target, "month_index"]
    return int(hit.iloc[0]) if len(hit) else None


def _summarise(df, a, cal, build_keys, run_keys, sq_cost) -> dict:
    target = val(a["score_model"]["target"])
    last = df.iloc[-1]
    best = df.loc[df["score"].idxmax()]
    annual_saving_y1 = float(df["handling_saving"].sum())
    full_effect_saving = float(last["handling_saving"] * 12)

    build = [_cost(a, k) for k in build_keys]
    run_ = [_cost(a, k) for k in run_keys]
    missing = [k for k, v in zip(list(build_keys) + list(run_keys), build + run_) if v is None]
    payback = None
    has_costs = bool(build_keys or run_keys)
    if has_costs and not missing:
        payback = payback_months(df, sum(build), sum(run_))

    return {
        "avg_days_month12": float(last["avg_days"]),
        "score_month12": float(last["score"]),
        "best_score": float(best["score"]),
        "best_score_month": int(best["month_index"]),
        "target": target,
        "target_met": bool(last["score"] >= target),
        "first_month_target_met": _first_month(df, "score", target),
        "static": {"days_month12": float(last["avg_days_static"]), "score_month12": float(last["score_static"]),
                   "first_month_target_met": _first_month(df, "score_static", target)},
        "queue": {"days_month12": float(last["avg_days_queue"]), "score_month12": float(last["score_queue"]),
                  "first_month_target_met": _first_month(df, "score_queue", target)},
        "headline_view": "queue" if val(a["queue_model"]["headline"]) else "static",
        "backlog_month12": float(last["backlog"]),
        # "cleared" = the queue is down to its working stock (only cases still inside their floor days)
        "backlog_cleared_month": _first_month(df.assign(cleared=(df["backlog"] <= df["working_stock"] + 1)
                                                        .astype(int)), "cleared", 1),
        "status_quo_annual_cost": sq_cost * 12,
        "annual_handling_cost_y1": float(df["handling_cost"].sum()),
        "annual_saving_y1": annual_saving_y1,
        "annual_saving_full_effect": full_effect_saving,
        "agents_cost_y1": float(df["agents_cost"].sum()),
        "build_cost": sum(build) if not missing else None,
        "run_cost_year": sum(run_) if not missing else None,
        "payback_months": payback,
        "has_costs": has_costs,
        "costs_missing": missing,
    }


def payback_months(df: pd.DataFrame, build_cost: float, run_cost_year: float, horizon: int = 120):
    """Months until cumulative (saving - run cost - agent cost) covers the build cost.
    After the modelled 12 months, the month-12 run rate continues. None if never."""
    monthly = list(df["handling_saving"] - df["agents_cost"] - run_cost_year / 12)
    steady = monthly[-1]
    cum = 0.0
    for m in range(1, horizon + 1):
        cum += monthly[m - 1] if m <= len(monthly) else steady
        if cum >= build_cost:
            return m
    return None


# ---------------------------------------------------------------------------
# Named scenarios, grid, exports
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_calibration() -> Calibration:
    return calibrate(load_assumptions())


def named_scenarios(a: dict | None = None, cal: Calibration | None = None) -> list[dict]:
    a = a or load_assumptions()
    cal = cal or get_calibration()
    out = []
    for s in a["scenarios"]:
        res = run(s["levers"], a, cal, build_cost_keys=s["build_cost_keys"], run_cost_keys=s["run_cost_keys"])
        res.update({"id": s["id"], "name": s["name"], "note": s.get("note", "")})
        out.append(res)
    return out


def lever_grid(a: dict, cal: Calibration) -> pd.DataFrame:
    steps = [0, 0.25, 0.5, 0.75, 1.0]
    rows = []
    for t, f, e, ag in itertools.product(steps, steps, steps, [0, 17, 35]):
        res = run({"transfers_removed": t, "info_only_first_contact": f,
                   "estimated_read_reduction": e, "calderfield_agents_restored": ag}, a, cal)
        s = res["summary"]
        rows.append({"transfers_removed": t, "info_only_first_contact": f, "estimated_read_reduction": e,
                     "calderfield_agents_restored": ag,
                     "avg_days_month12": s["avg_days_month12"], "score_month12": s["score_month12"],
                     "target_met": s["target_met"], "first_month_target_met": s["first_month_target_met"],
                     "score_static_month12": s["static"]["score_month12"],
                     "score_queue_month12": s["queue"]["score_month12"],
                     "backlog_month12": s["backlog_month12"],
                     "annual_saving_y1": s["annual_saving_y1"],
                     "annual_saving_full_effect": s["annual_saving_full_effect"]})
    return pd.DataFrame(rows)


def export(a: dict | None = None) -> None:
    a = a or load_assumptions()
    cal = calibrate(a)
    EXPORTS.mkdir(parents=True, exist_ok=True)
    frames = []
    for s in named_scenarios(a, cal):
        df = s["months"].copy()
        df.insert(0, "scenario_name", s["name"])
        df.insert(0, "scenario_id", s["id"])
        frames.append(df)
    pd.concat(frames).round(4).to_csv(EXPORTS / "scenarios.csv", index=False)
    lever_grid(a, cal).round(4).to_csv(EXPORTS / "lever_grid.csv", index=False)
    pd.DataFrame(cal.rows()).to_csv(EXPORTS / "calibration.csv", index=False)
    print("wrote scenarios.csv, lever_grid.csv, calibration.csv -> data/exports/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _fmt_money(x):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"${x:,.0f}"


def _print_summary(name: str, res: dict) -> None:
    s, lv = res["summary"], res["levers"]
    hit = s["first_month_target_met"]
    print(f"\n{name}")
    print("  levers: " + ", ".join(f"{k}={v:g}" for k, v in lv.items()))
    print(f"  month 12: {s['avg_days_month12']:.1f} days -> score {s['score_month12']:.2f} "
          f"(target {s['target']}: {'MET in month ' + str(hit) if hit else 'not met'})  [{s['headline_view']} view]")
    print(f"  static view: {s['static']['days_month12']:.1f} days, score {s['static']['score_month12']:.2f}"
          f" | queue view: {s['queue']['days_month12']:.1f} days, score {s['queue']['score_month12']:.2f}"
          + (f" (4.0 in month {s['queue']['first_month_target_met']})" if s['queue']['first_month_target_met'] else ""))
    print(f"  backlog month 12: {s['backlog_month12']:,.0f}  | handling saving y1 {_fmt_money(s['annual_saving_y1'])}"
          f", full effect {_fmt_money(s['annual_saving_full_effect'])}/yr")
    if s["costs_missing"]:
        print(f"  payback: set {', '.join(s['costs_missing'])} in assumptions.yaml")
    elif s["has_costs"]:
        pb = s["payback_months"]
        print(f"  payback: {str(pb) + ' months' if pb else 'never on handling savings alone'}"
              f" (build {_fmt_money(s['build_cost'])}, run {_fmt_money(s['run_cost_year'])}/yr)")


def main(argv=None):
    p = argparse.ArgumentParser(description="Northwind OneCase scenario engine")
    p.add_argument("--transfers", type=float, help="share of transfers removed, 0-1")
    p.add_argument("--info", type=float, help="share of information-only answered at first contact, 0-1")
    p.add_argument("--estimates", type=float, help="share of estimate-driven complaints avoided, 0-1")
    p.add_argument("--agents", type=float, help="Calderfield agents restored, 0-35")
    p.add_argument("--calibration", action="store_true", help="print data-derived numbers and exit")
    p.add_argument("--months", action="store_true", help="print the month-by-month table")
    p.add_argument("--no-export", action="store_true")
    args = p.parse_args(argv)

    a = load_assumptions()
    cal = calibrate(a)
    if args.calibration:
        for r in cal.rows():
            print(f"{r['name']:<45} {r['value']:>10}   {r['source']}")
        return
    custom = {k: v for k, v in {"transfers_removed": args.transfers, "info_only_first_contact": args.info,
                                "estimated_read_reduction": args.estimates,
                                "calderfield_agents_restored": args.agents}.items() if v is not None}
    if custom:
        res = run(custom, a, cal)
        _print_summary("Custom scenario", res)
        if args.months:
            print(res["months"].round(2).to_string(index=False))
        return
    for s in named_scenarios(a, cal):
        _print_summary(s["name"], s)
    if not args.no_export:
        export(a)


if __name__ == "__main__":
    main()
