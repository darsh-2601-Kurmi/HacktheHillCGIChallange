"""SIMULATED "before" path for a OneCase case: how the same complaint travels today.

The systems, their integration methods and notes come from northwind_systems.csv.
The odds and outcomes come from the complaints file for the intake system.
Nothing here is invented per case; the path is assembled from those two files.
"""
from __future__ import annotations

import pandas as pd

from .config import SMART_REGIONS, load_assumptions, val

# Typical intake system for each channel. The complaints file logs every channel in all four
# intake systems; this mapping is the simulation's choice, not a fact from the data.
INTAKE_BY_CHANNEL = {"Phone": "SYS-05", "Web form": "SYS-03", "Social": "SYS-03",
                     "Email": "SYS-04", "Post": "SYS-04", "Regulator referral": "SYS-04"}


# What the case needs from each system, grounded in that system's note in northwind_systems.csv.
STEP_TEXT = {
    "SYS-01": "Bill pulled from the 1998 mainframe to re-rate by hand.",
    "SYS-02": "Account and bill looked up in the customer system.",
    "SYS-06": "Read history checked; the estimate logic has not changed since 2012.",
    "SYS-07": "The smart read is here, but billing never received it.",
    "SYS-08": "Field visit booked; the engineer sees no complaint history.",
    "SYS-09": "Outage confirmed; billing reminders keep going out.",
    "SYS-10": "Water team works it in a system that was never integrated.",
    "SYS-14": "Letters pulled from the archive, 2-4 minutes each.",
}


def team_systems(team: str, region: str) -> list[str]:
    smart = region in SMART_REGIONS
    billing = "SYS-02" if smart else "SYS-01"   # Aurora Billing serves Barrowdale and Dunmoor only
    meter = "SYS-07" if smart else "SYS-06"
    return {
        "Billing resolution": [billing, meter],
        "Metering": ["SYS-06", "SYS-08"],
        "Network": ["SYS-09", billing],
        "Water operations": ["SYS-10"],
        "Field scheduling": ["SYS-08"],
        "Payments": [billing],
        "First-contact agent": ["SYS-02", "SYS-14"],
        "Complaints specialist": ["SYS-02", "SYS-14"],
    }.get(team, ["SYS-02"])


_STATS: dict = {}


def intake_stats(con, source_system: str) -> dict:
    if source_system in _STATS:
        return _STATS[source_system]
    c = pd.read_sql("SELECT source_system, transferred_between_systems AS t, days_to_close, sla_breach, reopened, "
                    "handling_unit_cost FROM complaint_360", con)
    s = c[c["source_system"] == source_system]
    by_t = c.groupby("t").agg(days=("days_to_close", "mean"), breach=("sla_breach", "mean"),
                              reopen=("reopened", "mean"), cost=("handling_unit_cost", "mean"))
    p = float(s["t"].mean())
    _STATS[source_system] = {
        "source_system": source_system,
        "complaints_logged": int(len(s)),
        "transfer_probability": p,
        "if_transferred": {k: float(v) for k, v in by_t.loc[1].items()},
        "if_not_transferred": {k: float(v) for k, v in by_t.loc[0].items()},
        "expected_days": p * by_t.loc[1, "days"] + (1 - p) * by_t.loc[0, "days"],
        "transferred_days": float(by_t.loc[1, "days"]),
    }
    return _STATS[source_system]


def legacy_path(con, case: dict) -> dict:
    region = con.execute("SELECT region FROM synth_accounts WHERE account_id=?", (case["account_id"],)).fetchone()[0]
    systems = {r["system_id"]: dict(r) for r in con.execute("SELECT * FROM systems")}
    intake = INTAKE_BY_CHANNEL.get(case["channel"], "SYS-04")
    team = (case.get("routing") or {}).get("owning_team", case["owning_team"])

    chain = [intake]
    if intake != "SYS-04":
        chain.append("SYS-04")  # the complaint must be re-keyed into CaseTrack
    chain += [s for s in team_systems(team, region) if s not in chain]

    hops = []
    for i, sid in enumerate(chain):
        s = systems[sid]
        batch = s["integration_method"] in ("Nightly batch file", "Manual export", "Batch interface")
        if i == 0:
            what, handoff = f"{case['channel']} contact logged in {s['system_name']}.", None
        elif sid == "SYS-04":
            what, handoff = "Complaint re-keyed into CaseTrack as a new record: transfer #1.", "rekey"
        else:
            what, handoff = STEP_TEXT.get(sid, f"{team} works the case here."), "batch" if batch else "live"
        hops.append({
            "system_id": sid, "system_name": s["system_name"], "year_installed": int(s["year_installed"]),
            "integration": s["integration_method"], "waits_for_batch": batch,
            "what_happens": what, "system_note": s["notes"],
            "handoff": handoff,   # how the case arrives here: rekey (history lost), batch (next day), live
            "history_carried": handoff in (None, "live"),
        })

    stats = intake_stats(con, intake)
    return {
        "simulated": True,
        "case_id": case["case_id"],
        "intake_system": intake,
        "hops": hops,
        "systems_touched": len(chain),
        "screens_for_agent": 4,  # SYS-05 note: "Agents run four systems side by side to answer one call."
        "stats": stats,
        "today_avg_days": val(load_assumptions()["baseline"]["avg_days_to_close"]),
        "onecase": {
            "systems_touched": 1, "screens_for_agent": 1, "transfers": 0,
            "reassignments": case.get("reassignments", 0),
            "status": case["status"], "minutes_to_resolve": case.get("minutes_to_resolve"),
            "history_kept": True,
        },
        "source": "northwind_systems.csv (systems, notes) + northwind_complaints.csv (odds, days)",
    }
