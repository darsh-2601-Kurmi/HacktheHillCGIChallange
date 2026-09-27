"""Phase 4: one test per routing rule, plus the key rule: a reassigned case keeps its ID and history."""
import pytest

from src import cases, routing
from src.synth_accounts import DEMO

NONE = {}
# (rule_id, category, priority, facts) -> the facts that should make exactly this rule fire first
CASES = [
    ("R01", "Billing - estimated read", "P3", {"estimate_with_smart_read": True}),
    ("R02", "Billing - estimated read", "P3", {"no_smart_meter": True}),
    ("R03", "Billing - estimated read", "P3", {"smart_meter": True}),
    ("R04", "Billing - disputed amount", "P3", {"estimate_with_smart_read": True, "explainable": True}),
    ("R05", "Billing - disputed amount", "P3", {"repeated_estimates_no_smart": True}),
    ("R06", "Billing - disputed amount", "P3", {"explainable": True}),
    ("R07", "Billing - disputed amount", "P3", {"bill_verified": True}),
    ("R08", "Billing - disputed amount", "P3", NONE),
    ("R09", "Metering - no read taken", "P3", {"smart_meter": True}),
    ("R10", "Metering - no read taken", "P3", {"no_smart_meter": True}),
    ("R11", "Supply - interruption", "P2", {"outage_active": True}),
    ("R12", "Supply - interruption", "P2", NONE),
    ("R13", "Water - pressure or quality", "P1", NONE),
    ("R14", "Water - pressure or quality", "P3", NONE),
    ("R15", "Service - missed appointment", "P3", NONE),
    ("R16", "Payment - plan or arrears", "P3", NONE),
    ("R17", "Service - poor communication", "P3", NONE),
    ("R18", "Other", "P3", {"explainable": True}),
    ("R19", "Other", "P3", NONE),
    ("R99", "Something new", "P3", NONE),
]


@pytest.mark.parametrize("rule_id,category,priority,facts", CASES)
def test_each_rule(rule_id, category, priority, facts):
    d = routing.route(category, priority, "Ashford", facts)
    assert d["rule_id"] == rule_id
    assert d["sla_days"] == routing.SLA_DAYS[priority]


def test_every_rule_in_the_table_is_tested():
    assert {r["rule_id"] for r in routing.load_rules()} == {c[0] for c in CASES}


def test_field_visit_flags():
    assert routing.route("Billing - estimated read", "P3", "Dunmoor", {"no_smart_meter": True})["needs_field_visit"]
    assert not routing.route("Billing - estimated read", "P3", "Ashford",
                             {"estimate_with_smart_read": True})["needs_field_visit"]


EXPECTED = {"A": ("R01", "Billing resolution", "estimate_with_smart_read"),
            "B": ("R02", "Metering", "repeated_estimates_no_smart"),
            "C": ("R06", "First-contact agent", "explainable"),
            "D": ("R11", "Network", "outage_active"),
            "E": ("R07", "First-contact agent", "bill_verified")}


@pytest.mark.parametrize("label", list(EXPECTED))
def test_demo_intake_routes(con, label):
    from src.api import DEMO_INTAKE
    cases.reset(con)
    c = cases.create_case(con, account_id=DEMO[label]["account_id"], **DEMO_INTAKE[label])
    rule, team, outcome = EXPECTED[label]
    assert (c["routing_rule"], c["owning_team"], c["bill_check"]["outcome"]) == (rule, team, outcome)
    assert c["transfers"] == 0


def test_reassign_keeps_case_id_and_history(con):
    cases.reset(con)
    c = cases.create_case(con, "Phone", DEMO["D"]["account_id"], "Supply - interruption", "power off", "P2")
    before = [e["id"] for e in c["timeline"]]
    c2 = cases.act(con, c["case_id"], "reassign", team="Billing resolution")
    c3 = cases.act(con, c["case_id"], "reassign", team="Metering")
    assert c2["case_id"] == c3["case_id"] == c["case_id"]
    assert [e["id"] for e in c3["timeline"]][:len(before)] == before       # history untouched
    assert c3["owning_team"] == "Metering" and c3["reassignments"] == 2
    assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1    # still one case
    assert c3["channel"] == "Phone"                                       # channel is just a field


def test_repeat_contact_joins_the_open_case(con):
    cases.reset(con)
    first = cases.create_case(con, "Web form", DEMO["A"]["account_id"], "Billing - estimated read")
    again = cases.create_case(con, "Phone", DEMO["A"]["account_id"], "Billing - disputed amount", "calling back")
    assert again["case_id"] == first["case_id"] and again["linked_existing"]
    assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
    assert "Repeat contact from Phone" in again["timeline"][-1]["summary"]
    cases.act(con, first["case_id"], "correct_bill")
    third = cases.create_case(con, "Phone", DEMO["A"]["account_id"], "Other")   # resolved: a new complaint
    assert third["case_id"] != first["case_id"]
