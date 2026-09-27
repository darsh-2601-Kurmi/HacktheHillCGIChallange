"""Phase 4: the OneCase store. One case per complaint, whatever the channel.

Key rule: a case is created ONCE. Channel is just a field. Reassigning to another team
changes `owning_team` on the same row and appends to the same timeline; the case ID
and its history never change. That is the whole point.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import billcheck, routing

CHANNELS = ["Phone", "Web form", "Email", "Social", "Post", "Regulator referral"]
CATEGORIES = ["Billing - disputed amount", "Billing - estimated read", "Metering - no read taken",
              "Supply - interruption", "Service - poor communication", "Service - missed appointment",
              "Payment - plan or arrears", "Water - pressure or quality", "Other"]
PRIORITIES = ["P1", "P2", "P3"]
ACTIONS = {"correct_bill", "book_visit", "explain", "hold_reminders", "reassign", "escalate", "note", "resolve"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, channel TEXT NOT NULL, category TEXT NOT NULL,
  priority TEXT NOT NULL, free_text TEXT, status TEXT NOT NULL, owning_team TEXT NOT NULL,
  routing_rule TEXT, sla_days INTEGER, created_at TEXT NOT NULL, due_at TEXT, resolved_at TEXT,
  resolution TEXT, needs_field_visit INTEGER DEFAULT 0, reassignments INTEGER DEFAULT 0,
  origin TEXT DEFAULT 'agent desktop');
CREATE TABLE IF NOT EXISTS case_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, ts TEXT NOT NULL, type TEXT NOT NULL,
  actor TEXT, summary TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS bill_adjustments (
  account_id TEXT NOT NULL, period TEXT NOT NULL, corrected_kwh REAL NOT NULL, corrected_amount REAL,
  case_id TEXT NOT NULL, ts TEXT NOT NULL, PRIMARY KEY (account_id, period));
CREATE INDEX IF NOT EXISTS ix_case_events ON case_events(case_id);
CREATE INDEX IF NOT EXISTS ix_cases_account ON cases(account_id);
"""


class CaseError(ValueError):
    pass


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def ensure_schema(con) -> None:
    con.executescript(SCHEMA)


def reset(con) -> dict:
    """Restore the demo to a clean state: no OneCase cases, no bill corrections."""
    ensure_schema(con)
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("cases", "case_events", "bill_adjustments")}
    con.executescript("DELETE FROM case_events; DELETE FROM cases; DELETE FROM bill_adjustments;"
                      "DELETE FROM sqlite_sequence WHERE name='case_events';")
    con.commit()
    return {"cleared": counts}


def _next_id(con) -> str:
    row = con.execute("SELECT MAX(CAST(SUBSTR(case_id, 4) AS INTEGER)) FROM cases").fetchone()
    return f"OC-{(row[0] or 10000) + 1}"


def _event(con, case_id, type_, summary, detail=None, actor="OneCase", ts=None):
    con.execute("INSERT INTO case_events (case_id, ts, type, actor, summary, detail) VALUES (?,?,?,?,?,?)",
                (case_id, (ts or now()).isoformat(sep=" "), type_, actor, summary,
                 json.dumps(detail) if detail is not None else None))


def _outage(con, region):
    row = con.execute("SELECT * FROM synth_outages WHERE region=? AND active=1", (region,)).fetchone()
    return dict(row) if row else None


# --------------------------------------------------------------------------- intake
def create_case(con, channel: str, account_id: str, category: str, free_text: str = "",
                priority: str = "P3", origin: str = "agent desktop", actor: str = "Agent") -> dict:
    ensure_schema(con)
    if channel not in CHANNELS:
        raise CaseError(f"unknown channel {channel!r}")
    if category not in CATEGORIES:
        raise CaseError(f"unknown category {category!r}")
    if priority not in PRIORITIES:
        raise CaseError(f"unknown priority {priority!r}")
    acc = con.execute("SELECT * FROM synth_accounts WHERE account_id=?", (account_id,)).fetchone()
    if acc is None:
        raise CaseError(f"account {account_id} not found")
    acc = dict(acc)

    # One case per complaint: a repeat contact while a case is open joins that case, whatever the channel.
    existing = con.execute("SELECT case_id FROM cases WHERE account_id=? AND status != 'Resolved' "
                           "ORDER BY created_at DESC LIMIT 1", (account_id,)).fetchone()
    if existing:
        _event(con, existing[0], "intake", f"Repeat contact from {channel}: added to open case {existing[0]}. "
               f"No new record, nothing to re-explain.", {"channel": channel, "category": category,
                                                          "free_text": free_text}, actor)
        con.commit()
        case = get_case(con, existing[0])
        case["linked_existing"] = True
        return case

    case_id, t0 = _next_id(con), now()
    _event(con, case_id, "intake", f"Case {case_id} opened from {channel}. One case, whatever the channel.",
           {"channel": channel, "category": category, "priority": priority, "free_text": free_text}, actor, t0)

    past = [dict(r) for r in con.execute(
        "SELECT complaint_id, date_opened, category, days_to_close, transferred_between_systems AS transferred, "
        "reopened FROM complaints WHERE account_id=? ORDER BY date_opened", (account_id,))]
    if past:
        _event(con, case_id, "history", f"Account history attached: {len(past)} past complaint"
               f"{'s' if len(past) > 1 else ''}, meter reads and 12 bills on this screen.", {"past": past},
               ts=t0)

    check = None
    if routing.needs_bill_check(category):
        check = billcheck.check_account(con, account_id)
        _event(con, case_id, "bill_check", f"Bill check: {check['headline']}.", check, ts=t0)
        facts = check["facts"]
    else:
        outage = _outage(con, acc["region"])
        facts = {"smart_meter": bool(acc["has_smart_meter"]), "no_smart_meter": not acc["has_smart_meter"],
                 "outage_active": outage is not None}

    decision = routing.route(category, priority, acc["region"], facts)
    _event(con, case_id, "routing", f"Routed once to {decision['owning_team']} ({decision['rule_id']}: "
           f"{decision['reason']}). SLA {decision['sla_days']} days.", decision, ts=t0)

    due = t0 + timedelta(days=decision["sla_days"])
    con.execute(
        "INSERT INTO cases (case_id, account_id, channel, category, priority, free_text, status, owning_team, "
        "routing_rule, sla_days, created_at, due_at, needs_field_visit, origin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (case_id, account_id, channel, category, priority, free_text, "Open", decision["owning_team"],
         decision["rule_id"], decision["sla_days"], t0.isoformat(sep=" "), due.isoformat(sep=" "),
         int(decision["needs_field_visit"]), origin))
    con.commit()
    return get_case(con, case_id)


# --------------------------------------------------------------------------- read
def get_case(con, case_id: str) -> dict | None:
    ensure_schema(con)
    row = con.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
    if row is None:
        return None
    case = dict(row)
    events = []
    for e in con.execute("SELECT * FROM case_events WHERE case_id=? ORDER BY id", (case_id,)):
        e = dict(e)
        e["detail"] = json.loads(e["detail"]) if e["detail"] else None
        events.append(e)
    case["timeline"] = events
    checks = [e["detail"] for e in events if e["type"] == "bill_check"]
    case["bill_check"] = checks[-1] if checks else None
    routes = [e["detail"] for e in events if e["type"] == "routing"]
    case["routing"] = routes[0] if routes else None
    if case["resolved_at"]:
        mins = (datetime.fromisoformat(case["resolved_at"]) - datetime.fromisoformat(case["created_at"]))
        case["minutes_to_resolve"] = round(mins.total_seconds() / 60, 1)
    case["transfers"] = 0  # by construction: the case never leaves the store
    return case


def list_cases(con, limit: int = 20, account_id: str | None = None) -> list[dict]:
    ensure_schema(con)
    q, args = "SELECT * FROM cases", []
    if account_id:
        q, args = q + " WHERE account_id=?", [account_id]
    return [dict(r) for r in con.execute(q + " ORDER BY created_at DESC, case_id DESC LIMIT ?", (*args, limit))]


# --------------------------------------------------------------------------- actions
def _set(con, case_id, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    con.execute(f"UPDATE cases SET {cols} WHERE case_id=?", (*fields.values(), case_id))


def _resolve(con, case_id, resolution, actor, ts):
    _set(con, case_id, status="Resolved", resolution=resolution, resolved_at=ts.isoformat(sep=" "))
    _event(con, case_id, "resolved", f"Resolved: {resolution}.", {"resolution": resolution}, actor, ts)


def _reassign(con, case, team, actor, ts, why=""):
    if team not in routing.TEAMS:
        raise CaseError(f"unknown team {team!r}")
    if team == case["owning_team"]:
        return
    _set(con, case["case_id"], owning_team=team, reassignments=case["reassignments"] + 1)
    _event(con, case["case_id"], "reassign",
           f"Reassigned from {case['owning_team']} to {team}. Same case {case['case_id']}, full history kept."
           + (f" {why}" if why else ""), {"from": case["owning_team"], "to": team}, actor, ts)
    case["owning_team"] = team


def act(con, case_id: str, action: str, team: str | None = None, note: str | None = None,
        actor: str = "Agent") -> dict:
    case = get_case(con, case_id)
    if case is None:
        raise CaseError(f"case {case_id} not found")
    if action not in ACTIONS:
        raise CaseError(f"unknown action {action!r}")
    if case["status"] == "Resolved" and action not in ("note", "reassign"):
        raise CaseError(f"case {case_id} is already resolved")
    ts = now()

    if action == "correct_bill":
        chk = case["bill_check"]
        rule1 = next((r for r in (chk or {}).get("rules", []) if r["rule"] == 1 and r["status"] == "flag"), None)
        if rule1 is None:
            raise CaseError("no estimate-with-smart-read flag on this case to correct")
        acc = con.execute("SELECT * FROM synth_bills WHERE account_id=? LIMIT 1", (case["account_id"],)).fetchone()
        for c in rule1["details"]["corrections"]:
            b = con.execute("SELECT days FROM synth_bills WHERE account_id=? AND period=?",
                            (case["account_id"], c["period"])).fetchone()
            amount = round(c["smart_kwh"] * acc["rate_per_kwh"] + b["days"] * acc["standing_charge_per_day"], 2)
            con.execute("INSERT OR REPLACE INTO bill_adjustments VALUES (?,?,?,?,?,?)",
                        (case["account_id"], c["period"], c["smart_kwh"], amount, case_id, ts.isoformat(sep=" ")))
        d = rule1["details"]
        _event(con, case_id, "action", f"Bills for {len(d['periods'])} month(s) re-issued on actual smart reads: "
               f"{'credit' if d['difference_dollars'] > 0 else 'charge'} of ${abs(d['difference_dollars']):,.2f}. "
               f"Unit cost $34, no field visit.", {"action": action, **d}, actor, ts)
        recheck = billcheck.check_account(con, case["account_id"])
        _event(con, case_id, "bill_check", f"Re-check after correction: {recheck['headline']}.", recheck, ts=ts)
        _resolve(con, case_id, "Bill corrected and re-issued", actor, ts)

    elif action == "book_visit":
        _reassign(con, case, "Metering", actor, ts)
        visit = ts + timedelta(days=3)
        _set(con, case_id, status="Field visit booked", needs_field_visit=1)
        _event(con, case_id, "action", f"Meter read booked for {visit:%a %d %b}. The engineer's job carries this "
               f"case and its full history (legacy: FieldForce has no link to CaseTrack).",
               {"action": action, "visit_date": visit.date().isoformat()}, actor, ts)

    elif action == "explain":
        chk = case["bill_check"]
        _event(con, case_id, "action", "Explanation given to the customer on first contact.",
               {"action": action, "script": chk["explanation"] if chk else note}, actor, ts)
        _resolve(con, case_id, "Information provided at first contact", actor, ts)

    elif action == "hold_reminders":
        _event(con, case_id, "action", "Billing reminders held for this account while the outage is active.",
               {"action": action}, actor, ts)
        _set(con, case_id, status="Open - reminders held")

    elif action == "reassign":
        if not team:
            raise CaseError("reassign needs a team")
        _reassign(con, case, team, actor, ts, note or "")

    elif action == "escalate":
        _reassign(con, case, "Complaints specialist", actor, ts, note or "")
        _set(con, case_id, status="Escalated")

    elif action == "note":
        _event(con, case_id, "note", note or "(empty note)", None, actor, ts)

    elif action == "resolve":
        _resolve(con, case_id, note or "Resolved", actor, ts)

    con.commit()
    return get_case(con, case_id)
