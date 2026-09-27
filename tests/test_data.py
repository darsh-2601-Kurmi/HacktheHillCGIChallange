"""Phase 1 validation: reproduce every diagnosis number we quote. Our proof if a judge challenges one."""
import numpy as np
import pandas as pd
import pytest

from src.config import EXPORTS, load_assumptions, val


@pytest.fixture(scope="module")
def cx(isolated_db):
    import src.config as cfg
    con = cfg.connect()
    df = pd.read_sql("SELECT * FROM complaint_360", con)
    con.close()
    return df


def q(sql):
    import src.config as cfg
    con = cfg.connect()
    df = pd.read_sql(sql, con)
    con.close()
    return df


def test_counts(cx):
    assert len(cx) == 25_416
    assert (cx["status"] == "Open").sum() == 1_599
    assert cx["date_closed"].isna().sum() == 1_599
    assert cx["days_to_close"].isna().sum() == 1_599
    assert cx["resolvable_by_information_only"].isna().sum() == 1_599


def test_transfer_rate_by_source_system(cx):
    rate = cx.groupby("source_system")["transferred_between_systems"].mean()
    assert rate["SYS-04"] == 0
    for s in ["SYS-01", "SYS-03", "SYS-05"]:
        assert rate[s] == pytest.approx(0.46, abs=0.015)


def test_transfer_rate_flat_across_everything_else(cx):
    # 32.9% ("Other", 671 cases) to 37.0%: flat. Only source_system moves it (0% vs 46%).
    cx = cx.assign(quarter=pd.PeriodIndex(cx["date_opened"], freq="Q").astype(str))
    for col in ["category", "channel", "priority", "region", "quarter"]:
        r = cx.groupby(col)["transferred_between_systems"].mean()
        assert r.between(0.32, 0.375).all(), col


def test_transferred_vs_not(cx):
    g = cx.groupby("transferred_between_systems").agg(
        days=("days_to_close", "mean"), breach=("sla_breach", "mean"), reopen=("reopened", "mean"), n=("complaint_id", "size"))
    assert g.loc[1, "days"] == pytest.approx(38.2, abs=0.05)
    assert g.loc[0, "days"] == pytest.approx(23.0, abs=0.05)
    assert g.loc[1, "breach"] == pytest.approx(0.89, abs=0.005)
    assert g.loc[0, "breach"] == pytest.approx(0.70, abs=0.005)
    assert g.loc[1, "reopen"] == pytest.approx(0.27, abs=0.005)
    assert g.loc[0, "reopen"] == pytest.approx(0.08, abs=0.005)
    assert g.loc[1, "n"] == 8_870
    assert g.loc[1, "n"] / len(cx) == pytest.approx(0.349, abs=0.001)


def test_unit_costs(cx):
    assert set(cx.loc[cx["transferred_between_systems"] == 1, "handling_unit_cost"]) == {121}
    assert set(cx.loc[cx["transferred_between_systems"] == 0, "handling_unit_cost"]) == {68}


def test_billing_and_metering_drive_volume(cx):
    est = cx["category"].isin(["Billing - disputed amount", "Billing - estimated read", "Metering - no read taken"])
    assert est.mean() == pytest.approx(0.63, abs=0.005)
    billing = cx[cx["category"].str.startswith("Billing")]
    fixed = billing["resolution_action"].isin(["Bill corrected and re-issued", "Refund or credit applied"])
    assert fixed.mean() == pytest.approx(0.59, abs=0.005)


def test_information_only(cx):
    info = cx[cx["resolvable_by_information_only"] == 1]
    assert len(info) == 5_865
    assert len(info) / len(cx) == pytest.approx(0.23, abs=0.005)
    assert info["days_to_close"].mean() == pytest.approx(28.0, abs=0.1)
    assert info["transferred_between_systems"].mean() == pytest.approx(0.34, abs=0.01)


def test_smart_meters_not_used_by_billing():
    m = q("SELECT * FROM meter_reads ORDER BY month")
    smart = m[m["region"].isin(["Ashford", "Calderfield", "Eastmarch", "Fenwick"])]
    first, last = smart[smart["month"] == "2024-10"], smart[smart["month"] == "2026-09"]
    assert first["smart_meter_penetration"].mean() == pytest.approx(0.30, abs=0.001)
    assert last["smart_meter_penetration"].mean() == pytest.approx(0.806, abs=0.001)
    by_month = smart.groupby("month")["estimated_read_rate"].mean()
    assert by_month.between(0.18, 0.26).all()   # flat, ~21-23% on average
    for r in ["Barrowdale", "Dunmoor"]:
        rm = m[m["region"] == r]
        assert rm["smart_meter_penetration"].max() == 0
        assert rm["estimated_read_rate"].mean() == pytest.approx(0.61, abs=0.04)


def test_ai_pilot_got_worse():
    p = q("SELECT * FROM ai_pilot ORDER BY month")
    assert p["fully_contained_rate"].is_monotonic_decreasing
    assert p["repeat_contact_within_7_days_rate"].is_monotonic_increasing
    assert p["assistant_csat_of_5"].iloc[0] == 2.6 and p["assistant_csat_of_5"].iloc[-1] == pytest.approx(2.04)


def test_calderfield_is_a_red_herring(cx):
    st = q("SELECT * FROM staffing WHERE region='Calderfield' ORDER BY month")
    assert st["agent_fte"].max() >= 72 and st["agent_fte"].iloc[-1] == 37
    recent = cx[cx["month_opened"] >= "2026-03"]
    g = recent.groupby("region").agg(days=("days_to_close", "mean"), breach=("sla_breach", "mean"))
    others = g.drop("Calderfield")
    assert abs(g.loc["Calderfield", "days"] - others["days"].mean()) < 1.5
    assert abs(g.loc["Calderfield", "breach"] - others["breach"].mean()) < 0.03


def test_score_regression():
    k = q("SELECT * FROM monthly_kpis ORDER BY month")
    slope, intercept = np.polyfit(k["avg_days_to_close"], k["regulator_satisfaction_score_of_5"], 1)
    r = np.corrcoef(k["avg_days_to_close"], k["regulator_satisfaction_score_of_5"])[0, 1]
    assert slope == pytest.approx(-0.069, abs=0.0005)
    assert intercept == pytest.approx(5.316, abs=0.001)
    assert r == pytest.approx(-0.98, abs=0.005)
    assert (4.0 - intercept) / slope == pytest.approx(19.0, abs=0.1)


def test_kpi_days_are_days_of_complaints_closed_that_month(cx):
    k = q("SELECT month, avg_days_to_close FROM monthly_kpis").set_index("month")["avg_days_to_close"]
    ours = cx.groupby("month_closed")["days_to_close"].mean().round(1)
    assert (ours.reindex(k.index) == k).all()


def test_assumptions_baseline_matches_data():
    a = load_assumptions()
    k = q("SELECT * FROM monthly_kpis ORDER BY month")
    b = a["baseline"]
    assert val(b["avg_days_to_close"]) == k["avg_days_to_close"].iloc[-1]
    assert val(b["regulator_score"]) == k["regulator_satisfaction_score_of_5"].iloc[-1]
    assert val(b["monthly_opened"]) == pytest.approx(k["complaints_opened"].tail(6).mean(), abs=0.5)
    assert val(b["monthly_closed"]) == pytest.approx(k["complaints_closed"].tail(6).mean(), abs=0.5)
    assert val(b["open_backlog"]) == q("SELECT COUNT(*) n FROM complaints WHERE status='Open'")["n"][0]
    sm = a["score_model"]
    slope, intercept = np.polyfit(k["avg_days_to_close"], k["regulator_satisfaction_score_of_5"], 1)
    assert val(sm["slope_per_day"]) == pytest.approx(slope, abs=0.0005)
    assert val(sm["intercept"]) == pytest.approx(intercept, abs=0.001)


def test_unit_costs_match_file():
    a = load_assumptions()
    u = q("SELECT key, unit_cost FROM unit_costs").set_index("key")["unit_cost"]
    for k, v in a["unit_costs"].items():
        assert val(v) == u[k], k


def test_exports_exist():
    for f in ["complaint_360", "region_month", "segment_summary", "backlog_month",
              "scenarios", "lever_grid", "calibration"]:
        assert (EXPORTS / f"{f}.csv").exists(), f
