"""Phase 2: scenario engine behaves: zero levers = baseline, every lever moves results the right way."""
import copy

import pytest

from src import scenario
from src.config import load_assumptions, val

LEVERS = scenario.LEVERS


@pytest.fixture(scope="module")
def a():
    return load_assumptions()


@pytest.fixture(scope="module")
def cal(a, isolated_db):
    return scenario.calibrate(a)


def run(a, cal, **lv):
    return scenario.run(lv, a, cal)


def test_zero_levers_reproduce_baseline(a, cal):
    res = run(a, cal)
    df = res["months"]
    assert (df["avg_days_static"] - val(a["baseline"]["avg_days_to_close"])).abs().max() < 1e-9
    assert (df["intake"] - val(a["baseline"]["monthly_opened"])).abs().max() < 1e-9
    assert df["closures"].iloc[0] == pytest.approx(val(a["baseline"]["monthly_closed"]))
    growth = val(a["baseline"]["monthly_opened"]) - val(a["baseline"]["monthly_closed"])
    assert df["backlog"].iloc[0] == pytest.approx(val(a["baseline"]["open_backlog"]) + growth)
    assert df["handling_saving"].abs().max() == pytest.approx(0, abs=1e-6)
    sm = a["score_model"]
    assert res["summary"]["score_month12"] == pytest.approx(val(sm["intercept"]) + val(sm["slope_per_day"]) * 38.2)


@pytest.mark.parametrize("lever,top", [("transfers_removed", 1), ("info_only_first_contact", 1),
                                       ("estimated_read_reduction", 1), ("calderfield_agents_restored", 35)])
def test_each_lever_is_monotonic(a, cal, lever, top):
    prev = None
    for step in [0, 0.25, 0.5, 0.75, 1.0]:
        s = run(a, cal, **{lever: step * top})["summary"]
        cur = (s["static"]["days_month12"], s["queue"]["days_month12"], s["backlog_month12"],
               s["score_month12"], s["annual_saving_y1"])
        if prev:
            assert cur[0] <= prev[0] + 1e-9     # static days never rise
            assert cur[1] <= prev[1] + 1e-9     # queue days never rise
            assert cur[2] <= prev[2] + 1e-9     # backlog never rises
            assert cur[3] >= prev[3] - 1e-9     # score never falls
            if lever != "calderfield_agents_restored":
                assert cur[4] >= prev[4] - 1e-6  # handling saving never falls
        prev = cur


def test_no_double_counting_of_overlap(a, cal):
    base = 38.2
    t = base - run(a, cal, transfers_removed=1)["summary"]["static"]["days_month12"]
    f = base - run(a, cal, info_only_first_contact=1)["summary"]["static"]["days_month12"]
    both = base - run(a, cal, transfers_removed=1, info_only_first_contact=1)["summary"]["static"]["days_month12"]
    assert both < t + f
    # the overlap is exactly the transfer saving on info-only transferred cases
    c = cal.cells
    overlap = c[(1, 1)]["share"] * (c[(1, 1)]["days"] - c[(1, 0)]["days"])
    assert t + f - both == pytest.approx(overlap, rel=1e-6)


def test_transfers_alone_reach_about_three(a, cal):
    s = run(a, cal, transfers_removed=1)["summary"]
    assert s["static"]["score_month12"] == pytest.approx(3.0, abs=0.1)
    assert not s["target_met"]


def test_levers_are_clamped(a, cal):
    lv = scenario.clean_levers({"transfers_removed": 5, "calderfield_agents_restored": -3}, a)
    assert lv["transfers_removed"] == 1 and lv["calderfield_agents_restored"] == 0


def test_named_scenarios(a, cal):
    named = {s["id"]: s for s in scenario.named_scenarios(a, cal)}
    assert list(named) == ["status_quo", "client_ai_plan", "routing_fix", "recommended", "everything_max"]
    score = {k: v["summary"]["score_month12"] for k, v in named.items()}
    assert score["status_quo"] < score["client_ai_plan"] < score["routing_fix"] < score["recommended"] \
        <= score["everything_max"]
    assert len(named["recommended"]["months"]) == 12


def test_tbd_blocks_payback_and_values_unblock_it(a, cal):
    rec = next(s for s in a["scenarios"] if s["id"] == "recommended")
    res = scenario.run(rec["levers"], a, cal, build_cost_keys=rec["build_cost_keys"],
                       run_cost_keys=rec["run_cost_keys"])
    assert res["summary"]["payback_months"] is None
    assert "onecase_build_cost" in res["summary"]["costs_missing"]
    b = copy.deepcopy(a)
    for k, v in {"onecase_build_cost": 300_000, "billing_feedback_loop_cost": 100_000,
                 "onecase_run_cost_year": 50_000}.items():
        b["team_estimates"][k]["value"] = v
    res = scenario.run(rec["levers"], b, cal, build_cost_keys=rec["build_cost_keys"],
                       run_cost_keys=rec["run_cost_keys"])
    assert res["summary"]["costs_missing"] == []
    assert 1 <= res["summary"]["payback_months"] <= 36


def test_status_quo_has_no_payback(a, cal):
    s = next(x for x in scenario.named_scenarios(a, cal) if x["id"] == "status_quo")
    assert s["summary"]["payback_months"] is None and not s["summary"]["has_costs"]
