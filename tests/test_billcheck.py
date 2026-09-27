"""Phase 5: every bill check rule, on the demo accounts and on hand-made inputs."""
import pytest

from src import billcheck, cases
from src.synth_accounts import DEMO, PERIODS


def check(con, label):
    return billcheck.check_account(con, DEMO[label]["account_id"])


def test_A_estimate_with_smart_read_is_overbilled(con):
    r = check(con, "A")
    assert r["outcome"] == "estimate_with_smart_read" and r["status"] == "flag"
    assert r["difference_dollars"] == pytest.approx(171.08)
    assert r["action"]["code"] == "correct_bill" and r["action"]["unit_cost"] == 34
    assert "July 2026, August 2026 and September 2026" in r["explanation"]
    assert "$171.08" in r["explanation"]
    assert "based on an estimate, although a smart reading exists" in r["breakdown"]


def test_B_repeated_estimates_needs_a_read(con):
    r = check(con, "B")
    assert r["outcome"] == "repeated_estimates_no_smart"
    assert r["action"]["code"] == "book_visit" and r["solvable_remotely"] is False
    assert "last 4 bills" in r["explanation"]


def test_C_seasonal_explanation(con):
    r = check(con, "C")
    assert r["outcome"] == "explainable" and r["status"] == "info"
    assert r["headline"] == "Seasonal: bill is correct"
    assert "last September you used 402 kWh" in r["explanation"]
    assert r["action"]["code"] == "explain"


def test_D_outage_holds_reminders(con):
    r = check(con, "D")
    assert r["outcome"] == "outage_active"
    assert r["facts"]["bill_verified"] and r["facts"]["outage_active"]
    assert "Fenwick" in r["explanation"]


def test_E_clean_account_is_verified(con):
    r = check(con, "E")
    assert r["outcome"] == "bill_verified" and r["status"] == "pass"
    assert "is correct" in r["explanation"] and "$89.02" in r["explanation"]
    assert all(x["status"] in ("pass", "n/a") for x in r["rules"])


def test_correction_clears_the_flag(con):
    cases.reset(con)
    c = cases.create_case(con, "Phone", DEMO["A"]["account_id"], "Billing - estimated read")
    c = cases.act(con, c["case_id"], "correct_bill")
    assert c["status"] == "Resolved" and c["bill_check"]["outcome"] == "bill_verified"
    assert check(con, "A")["outcome"] == "bill_verified"
    cases.reset(con)
    assert check(con, "A")["outcome"] == "estimate_with_smart_read"   # reset restores the demo


# ---- pure-function edge cases -------------------------------------------------------------
def make(kwh_billed, kwh_read, est, smart=True, rate=0.28):
    bills = [{"period": p, "billed_kwh": b, "read_type_used": "estimated" if e else "actual", "days": 30,
              "rate_per_kwh": rate, "standing_charge_per_day": 0.5, "corrected_kwh": None}
             for p, b, e in zip(PERIODS, kwh_billed, est)]
    reads = [{"period": p, "read_type": "smart" if smart else ("estimated" if e else "manual"),
              "read_kwh": r} for p, r, e in zip(PERIODS, kwh_read, est)]
    acc = {"account_id": "T", "region": "Ashford", "has_smart_meter": int(smart)}
    return acc, bills, reads


CFG = {"min_difference_dollars": 5, "consecutive_estimates": 3, "recent_increase_ratio": 1.15,
       "seasonal_band": 0.15, "usage_up_vs_last_year": 1.3, "cost_correction": 34, "cost_visit": 92,
       "cost_call": 7.4, "outage": None}


def test_small_difference_is_ignored():
    use = [300] * 13
    billed = use[:12] + [310]  # 10 kWh = $2.80 < $5
    r = billcheck.check(*make(billed, use, [False] * 12 + [True]), CFG)
    assert r["outcome"] == "bill_verified"


def test_underbilling_is_flagged_too():
    use = [300] * 13
    billed = use[:12] + [200]
    r = billcheck.check(*make(billed, use, [False] * 12 + [True]), CFG)
    assert r["outcome"] == "estimate_with_smart_read" and r["difference_dollars"] < 0
    assert r["headline"] == "Under-billed on estimates"


def test_two_estimates_without_smart_meter_do_not_flag():
    use = [300] * 13
    r = billcheck.check(*make(use, use[:11] + [None, None], [False] * 11 + [True, True], smart=False), CFG)
    assert r["outcome"] != "repeated_estimates_no_smart"
    r = billcheck.check(*make(use, use[:10] + [None] * 3, [False] * 10 + [True] * 3, smart=False), CFG)
    assert r["outcome"] == "repeated_estimates_no_smart"


def test_usage_up_vs_last_year():
    use = [300] * 12 + [450]  # +50% on last year and on recent months
    r = billcheck.check(*make(use, use, [False] * 13), CFG)
    assert r["outcome"] == "explainable" and "50% more than last September" in r["explanation"]


def test_outage_rule():
    use = [300] * 13
    cfg = {**CFG, "outage": {"since": "2026-09-25", "reference": "X-1", "region": "Ashford"}}
    r = billcheck.check(*make(use, use, [False] * 13), cfg)
    assert r["outcome"] == "outage_active" and r["action"]["code"] == "hold_reminders"
