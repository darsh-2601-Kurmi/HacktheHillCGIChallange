"""Phase 9: the value case refuses TBDs and its numbers match the engine."""
import copy

import pytest

from src import scenario, valuecase
from src.config import load_assumptions

COSTS = {"onecase_build_cost": 1_200_000, "onecase_run_cost_year": 250_000, "billing_feedback_loop_cost": 400_000,
         "penalty_quarters_at_risk": 2, "penalty_probability": 0.5}


def filled():
    a = copy.deepcopy(load_assumptions())
    for k, v in COSTS.items():
        a["team_estimates"][k]["value"] = v
    return a


def test_refuses_while_tbd(isolated_db):
    with pytest.raises(valuecase.TBDError):
        valuecase.build(load_assumptions())


def test_numbers_match_engine(isolated_db):
    a = filled()
    md = valuecase.build(a)
    rec = next(s for s in a["scenarios"] if s["id"] == "recommended")
    s = scenario.run(rec["levers"], a, scenario.calibrate(a))["summary"]
    assert f"{s['static']['score_month12']:.2f} by month 12" in md
    assert "$1.60M to build" in md
    for section in ["## 1. Cost", "## 2. Benefit by year", "## 3. Payback", "## 4. Assumptions",
                    "## 5. Sensitivity", "## 6. What this does not fix", "## 7. Stop doing"]:
        assert section in md


def test_html_version(isolated_db):
    h = valuecase.to_html(valuecase.build(filled()))
    assert h.count("<table>") == 4 and "@page" in h


def test_html_keeps_inline_formatting():
    assert valuecase._inline("**Ask:** run `x` *now*") == "<b>Ask:</b> run <code>x</code> <i>now</i>"
