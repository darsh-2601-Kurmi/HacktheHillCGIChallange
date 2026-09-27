"""Phase 5: bill check. Rules, not AI: explainable, testable and cheap.

Compares what was charged with the digital read. Rules run in order; each returns
status (flag / info / pass / n/a), a plain-language explanation an agent can read out,
and a suggested action. The first flag wins; otherwise the first info; otherwise verified.

  1. Estimate used while a smart read exists       -> flag, correct and re-issue ($34 vs $92 visit)
  2. >= 3 consecutive estimates, no smart meter     -> flag, book a meter read (not solvable remotely)
  3. Latest bill much higher, based on an actual read -> info, explain usage or season
  4. Active outage in the region                    -> info, hold billing reminders (SYS-09 note)
  5. Everything consistent                          -> pass, "Bill verified" with a breakdown
"""
from __future__ import annotations

import calendar

from .config import load_assumptions, val

WINDOW = 12  # bills shown and checked; the 13th (oldest) period only serves the same-month-last-year test


def month_name(period: str) -> str:
    y, m = map(int, period.split("-"))
    return f"{calendar.month_name[m]} {y}"


def _span(periods: list[str]) -> str:
    names = [month_name(p) for p in periods]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _money(x: float) -> str:
    return f"${abs(x):,.2f}"


def effective_bills(bills: list[dict], adjustments: dict) -> list[dict]:
    """Apply corrections: a OneCase adjustment beats a historical correction beats the original."""
    out = []
    for b in sorted(bills, key=lambda r: r["period"]):
        b = dict(b)
        adj = adjustments.get(b["period"])
        if adj is not None:
            b["effective_kwh"], b["corrected"], b["corrected_by"] = adj["corrected_kwh"], True, adj["case_id"]
        elif b.get("corrected_kwh") is not None:
            b["effective_kwh"], b["corrected"] = b["corrected_kwh"], True
        else:
            b["effective_kwh"], b["corrected"] = b["billed_kwh"], False
        b["effective_amount"] = round(b["effective_kwh"] * b["rate_per_kwh"]
                                      + b["days"] * b["standing_charge_per_day"], 2)
        out.append(b)
    return out


def breakdown(bill: dict, read: dict | None) -> str:
    kwh, rate = bill["effective_kwh"], bill["rate_per_kwh"]
    energy = kwh * rate
    standing = bill["days"] * bill["standing_charge_per_day"]
    smart = bool(read and read["read_type"] == "smart")
    if bill["corrected"]:
        basis = f"your actual {'smart ' if smart else ''}reading (corrected bill)"
    elif bill["read_type_used"] == "estimated":
        basis = "an estimate" + (", although a smart reading exists" if smart else "")
    else:
        basis = "an actual smart reading" if smart else "an actual meter reading"
    return (f"{month_name(bill['period'])}: {kwh:,.0f} kWh x ${rate:.2f} = ${energy:,.2f}, plus standing charge "
            f"{bill['days']} days x ${bill['standing_charge_per_day']:.2f} = ${standing:,.2f}. "
            f"Total ${energy + standing:,.2f}, based on {basis}.")


# --------------------------------------------------------------------------- rules
def rule_estimate_with_smart_read(bills, reads, account, cfg):
    rows = [b for b in bills[-WINDOW:] if b["read_type_used"] == "estimated" and not b["corrected"]
            and reads.get(b["period"], {}).get("read_type") == "smart"]
    res = {"rule": 1, "name": "Estimate used while a smart read exists"}
    if not rows:
        return {**res, "status": "pass", "explanation": "Every bill used the smart read where one existed."}
    diff_kwh = sum(b["billed_kwh"] - reads[b["period"]]["read_kwh"] for b in rows)
    diff = round(diff_kwh * rows[0]["rate_per_kwh"], 2)
    if abs(diff) < cfg["min_difference_dollars"]:
        return {**res, "status": "pass", "explanation": "Estimates were used but match the smart reads closely."}
    periods = [b["period"] for b in rows]
    if diff > 0:
        text = (f"Your {'bill' if len(rows) == 1 else 'bills'} for {_span(periods)} "
                f"{'was' if len(rows) == 1 else 'were'} based on estimates, even though your smart meter sent "
                f"actual readings for {'that month' if len(rows) == 1 else 'those months'}. You were charged for "
                f"{diff_kwh:,.0f} kWh more than you used, which is {_money(diff)}. We can correct and re-issue "
                f"{'it' if len(rows) == 1 else 'them'} now using your actual readings.")
    else:
        text = (f"Your bills for {_span(periods)} were based on estimates although your smart meter sent actual "
                f"readings. You were charged for {-diff_kwh:,.0f} kWh less than you used ({_money(diff)}). "
                f"We'll re-issue them with the actual readings so you don't get a large catch-up bill later.")
    return {**res, "status": "flag", "explanation": text,
            "action": {"code": "correct_bill", "label": "Correct and re-issue",
                       "unit_cost": cfg["cost_correction"],
                       "alternative": f"Field visit ${cfg['cost_visit']:.0f}: not needed, the smart read is already here"},
            "details": {"periods": periods, "difference_kwh": diff_kwh, "difference_dollars": diff,
                        "corrections": [{"period": b["period"], "billed_kwh": b["billed_kwh"],
                                         "smart_kwh": reads[b["period"]]["read_kwh"]} for b in rows]},
            "solvable_remotely": True}


def rule_repeated_estimates(bills, reads, account, cfg):
    res = {"rule": 2, "name": "Repeated estimates, no smart meter"}
    if account["has_smart_meter"]:
        return {**res, "status": "n/a", "explanation": "Account has a smart meter."}
    run = []
    for b in reversed(bills[-WINDOW:]):
        if b["read_type_used"] != "estimated" or b["corrected"]:
            break
        run.append(b["period"])
    run.reverse()
    if len(run) < cfg["consecutive_estimates"]:
        return {**res, "status": "pass", "explanation": "Recent bills are based on actual meter readings."}
    return {**res, "status": "flag",
            "explanation": (f"Your last {len(run)} bills ({_span([run[0], run[-1]]).replace(' and ', ' to ')}) "
                            f"were estimated because no meter reading was taken. Without a smart meter we can't "
                            f"check them remotely. We'll book a meter reading, and your next bill will be "
                            f"corrected to the actual reading."),
            "action": {"code": "book_visit", "label": "Book a meter read", "unit_cost": cfg["cost_visit"],
                       "alternative": "Customer can submit their own reading online"},
            "details": {"periods": run, "consecutive_estimates": len(run)},
            "solvable_remotely": False}


def rule_usage_change(bills, reads, account, cfg):
    res = {"rule": 3, "name": "Bill much higher, based on an actual read"}
    latest, prev = bills[-1], bills[-4:-1]
    if latest["read_type_used"] != "actual":
        return {**res, "status": "n/a", "explanation": "Latest bill is an estimate; see rules 1 and 2."}
    prev_avg = sum(b["effective_kwh"] for b in prev) / len(prev)
    ratio = latest["effective_kwh"] / prev_avg
    if ratio < cfg["recent_increase_ratio"]:
        return {**res, "status": "pass", "explanation": "Latest bill is in line with recent months."}
    ly_period = f"{int(latest['period'][:4]) - 1}{latest['period'][4:]}"
    ly = next((b for b in bills if b["period"] == ly_period), None)
    month = calendar.month_name[int(latest["period"][5:])]
    prev_span = f"{calendar.month_name[int(prev[0]['period'][5:])]} to {calendar.month_name[int(prev[-1]['period'][5:])]}"
    head = (f"Your {month} bill is higher because you used more energy: {latest['effective_kwh']:,.0f} kWh, "
            f"up from an average of {prev_avg:,.0f} kWh in {prev_span}. It is based on an actual reading, "
            f"not an estimate.")
    kind = "usage"
    if ly:
        yoy = latest["effective_kwh"] / ly["effective_kwh"]
        if abs(yoy - 1) <= cfg["seasonal_band"]:
            kind = "seasonal"
            head += (f" This is the normal seasonal pattern for your home: last {month} you used "
                     f"{ly['effective_kwh']:,.0f} kWh ({(yoy - 1) * 100:+.0f}%). Nothing is wrong with the bill.")
        elif yoy >= cfg["usage_up_vs_last_year"]:
            head += (f" That is {(yoy - 1) * 100:.0f}% more than last {month} ({ly['effective_kwh']:,.0f} kWh), "
                     f"so it is worth checking for a new appliance or heating change. We can send an energy-use guide.")
    return {**res, "status": "info", "kind": kind, "explanation": head,
            "action": {"code": "explain", "label": "Explain to customer", "unit_cost": cfg["cost_call"],
                       "alternative": "Information-only: close at first contact"},
            "details": {"latest_kwh": latest["effective_kwh"], "previous_avg_kwh": round(prev_avg, 1),
                        "ratio": round(ratio, 3), "last_year_kwh": ly["effective_kwh"] if ly else None},
            "solvable_remotely": True}


def rule_outage(bills, reads, account, cfg):
    res = {"rule": 4, "name": "Active outage in the region"}
    o = cfg.get("outage")
    if not o:
        return {**res, "status": "pass", "explanation": f"No active outage in {account['region']}."}
    return {**res, "status": "info",
            "explanation": (f"There is an active power outage in {account['region']} (since {o['since']}, "
                            f"reference {o['reference']}). Billing reminders for this account are on hold until "
                            f"it is resolved."),
            "action": {"code": "hold_reminders", "label": "Hold billing reminders", "unit_cost": 0,
                       "alternative": "Legacy: GridWatch outage data never reaches billing (SYS-09)"},
            "details": dict(o), "solvable_remotely": True}


RULES = [rule_estimate_with_smart_read, rule_repeated_estimates, rule_usage_change, rule_outage]

OUTCOMES = {  # rule number + status -> outcome code for routing and the UI
    (1, "flag"): "estimate_with_smart_read",
    (2, "flag"): "repeated_estimates_no_smart",
    (3, "info"): "explainable",
    (4, "info"): "outage_active",
}


def config(assumptions: dict | None = None, outage: dict | None = None) -> dict:
    a = assumptions or load_assumptions()
    bc, uc = a["bill_check"], a["unit_costs"]
    cfg = {k: val(v) for k, v in bc.items()}
    cfg.update({"cost_correction": val(uc["bill_correction"]), "cost_visit": val(uc["field_visit"]),
                "cost_call": val(uc["call"]), "outage": outage})
    return cfg


def check(account: dict, bills: list[dict], reads: list[dict], cfg: dict, adjustments: dict | None = None) -> dict:
    """Pure function: run every rule and pick the outcome."""
    eff = effective_bills(bills, adjustments or {})
    by_period = {r["period"]: r for r in reads}
    results = [rule(eff, by_period, account, cfg) for rule in RULES]
    flags = [r for r in results if r["status"] == "flag"]
    infos = [r for r in results if r["status"] == "info"]
    primary = (flags or infos or [None])[0]
    latest = eff[-1]
    bd = breakdown(latest, by_period.get(latest["period"]))
    if primary is None:
        primary = {"rule": 5, "name": "Everything consistent", "status": "pass",
                   "explanation": f"Your {month_name(latest['period'])} bill is correct. {bd}",
                   "action": {"code": "explain", "label": "Confirm bill is correct", "unit_cost": cfg["cost_call"],
                              "alternative": "Send the breakdown by email"}, "solvable_remotely": True}
        outcome = "bill_verified"
    else:
        outcome = OUTCOMES[(primary["rule"], primary["status"])]
    facts = {o: any(OUTCOMES.get((r["rule"], r["status"])) == o for r in results) for o in OUTCOMES.values()}
    facts["bill_verified"] = not flags and not any(r["rule"] == 3 and r["status"] == "info" for r in results)
    facts["smart_meter"] = bool(account["has_smart_meter"])
    facts["no_smart_meter"] = not facts["smart_meter"]
    return {
        "account_id": account["account_id"],
        "outcome": outcome,
        "status": primary["status"],
        "headline": {"estimate_with_smart_read": "Over-billed on estimates" if (primary.get("details") or {})
                     .get("difference_dollars", 0) > 0 else "Under-billed on estimates",
                     "repeated_estimates_no_smart": "Needs a meter read",
                     "explainable": "Higher bill explained" if primary.get("kind") != "seasonal"
                     else "Seasonal: bill is correct",
                     "outage_active": "Outage: reminders on hold",
                     "bill_verified": "Bill verified"}[outcome],
        "explanation": primary["explanation"],
        "action": primary.get("action"),
        "difference_dollars": (primary.get("details") or {}).get("difference_dollars"),
        "solvable_remotely": primary.get("solvable_remotely", True),
        "breakdown": bd,
        "facts": facts,
        "rules": results + ([primary] if outcome == "bill_verified" else []),
        "synthetic_data": True,
    }


# --------------------------------------------------------------------------- DB wrapper
def load_account(con, account_id: str):
    acc = con.execute("SELECT * FROM synth_accounts WHERE account_id = ?", (account_id,)).fetchone()
    if acc is None:
        return None
    bills = [dict(r) for r in con.execute("SELECT * FROM synth_bills WHERE account_id = ? ORDER BY period",
                                          (account_id,))]
    for b in bills:  # SQLite hands back NaN for missing floats written by pandas
        if b["corrected_kwh"] is not None and b["corrected_kwh"] != b["corrected_kwh"]:
            b["corrected_kwh"] = None
    reads = [dict(r) for r in con.execute("SELECT * FROM synth_reads WHERE account_id = ? ORDER BY period",
                                          (account_id,))]
    for r in reads:
        if r["read_kwh"] is not None and r["read_kwh"] != r["read_kwh"]:
            r["read_kwh"] = None
    adj = {}
    if _has_table(con, "bill_adjustments"):
        adj = {r["period"]: dict(r) for r in con.execute(
            "SELECT * FROM bill_adjustments WHERE account_id = ?", (account_id,))}
    outage = con.execute("SELECT * FROM synth_outages WHERE region = ? AND active = 1",
                         (acc["region"],)).fetchone()
    return dict(acc), bills, reads, adj, (dict(outage) if outage else None)


def _has_table(con, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def check_account(con, account_id: str, assumptions: dict | None = None) -> dict | None:
    loaded = load_account(con, account_id)
    if loaded is None:
        return None
    acc, bills, reads, adj, outage = loaded
    return check(acc, bills, reads, config(assumptions, outage), adj)
