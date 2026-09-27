"""Phase 4: intake routing. A declarative rules table (data/routing_rules.csv), first match wins.

Each rule matches on category, priority and region ('*' = any) plus one condition from a
fixed vocabulary. Conditions are facts about the account, most of them from the bill check:

  always                      always true
  estimate_with_smart_read    bill check rule 1 flagged
  repeated_estimates_no_smart bill check rule 2 flagged
  explainable                 bill check rule 3 (higher bill, actual read)
  bill_verified               no bill check flag and nothing to explain
  outage_active               active outage in the account's region
  smart_meter / no_smart_meter

The routing decision never creates a second case: the team is just a field on the one case.
"""
from __future__ import annotations

import csv
from functools import lru_cache

from .config import ROUTING_RULES_PATH

CONDITIONS = {"always", "estimate_with_smart_read", "repeated_estimates_no_smart", "explainable",
              "bill_verified", "outage_active", "smart_meter", "no_smart_meter"}
SLA_DAYS = {"P1": 5, "P2": 10, "P3": 20}  # northwind_complaints.csv: each priority has exactly one sla_days
TEAMS = ["First-contact agent", "Billing resolution", "Metering", "Network", "Water operations",
         "Field scheduling", "Payments", "Complaints specialist"]
# A category gets a bill check when any of its rules depends on account facts.
BILL_CHECK_CONDITIONS = CONDITIONS - {"always"}


@lru_cache(maxsize=1)
def load_rules(path=ROUTING_RULES_PATH) -> tuple[dict, ...]:
    with open(path, newline="", encoding="utf-8") as f:
        rules = [dict(r) for r in csv.DictReader(f)]
    for r in rules:
        if r["condition"] not in CONDITIONS:
            raise ValueError(f"{r['rule_id']}: unknown condition {r['condition']!r}")
        if r["owning_team"] not in TEAMS:
            raise ValueError(f"{r['rule_id']}: unknown team {r['owning_team']!r}")
        r["needs_field_visit"] = r["needs_field_visit"] == "yes"
        r["first_contact"] = r["first_contact"] == "yes"
    return tuple(rules)


def needs_bill_check(category: str) -> bool:
    """Billing, metering, supply and 'Other' complaints get a bill check; water, appointments,
    payments and communication complaints route on category alone."""
    return any(r["category"] == category and r["condition"] in BILL_CHECK_CONDITIONS for r in load_rules())


def route(category: str, priority: str, region: str, facts: dict) -> dict:
    """Return the first matching rule as a routing decision."""
    for r in load_rules():
        if r["category"] not in ("*", category) or r["priority"] not in ("*", priority) \
                or r["region"] not in ("*", region):
            continue
        if r["condition"] == "always" or facts.get(r["condition"]):
            return {
                "rule_id": r["rule_id"],
                "owning_team": r["owning_team"],
                "needs_field_visit": r["needs_field_visit"],
                "first_contact": r["first_contact"],
                "sla_days": SLA_DAYS.get(priority, 20),
                "condition": r["condition"],
                "reason": r["note"],
            }
    raise LookupError("no routing rule matched; R99 should always match")
