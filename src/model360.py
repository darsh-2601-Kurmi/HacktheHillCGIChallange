"""Phase 1b: joined views for the diagnosis report and the scenario engine.

Run:  python -m src.model360   (after src.load)
Builds tables complaint_360, region_month, segment_summary, backlog_month
and writes them to data/exports/*.csv.
"""
from __future__ import annotations

import pandas as pd

from .config import EXPORTS, connect

ESTIMATE_DRIVEN = ["Billing - disputed amount", "Billing - estimated read", "Metering - no read taken"]
# The two categories the billing feedback loop can actually prevent (plan, phase 2).
ESTIMATE_CATEGORIES = ["Billing - estimated read", "Metering - no read taken"]
CORRECTION_ACTIONS = ["Bill corrected and re-issued", "Refund or credit applied"]


def read(con, table: str) -> pd.DataFrame:
    return pd.read_sql(f"SELECT * FROM {table}", con)


def build_complaint_360(con) -> pd.DataFrame:
    c = read(con, "complaints")
    s = read(con, "systems")
    m = read(con, "meter_reads")
    st = read(con, "staffing")
    u = read(con, "unit_costs").set_index("key")["unit_cost"]

    sys_cols = s[["system_id", "system_name", "year_installed", "integration_method", "notes"]].rename(
        columns={"system_id": "source_system", "system_name": "source_system_name",
                 "year_installed": "source_system_year", "integration_method": "source_integration",
                 "notes": "source_system_notes"})
    meter_cols = m.rename(columns={"month": "month_opened", "accounts": "region_accounts",
                                   "systems_serving_region": "region_systems"})
    staff_cols = st[["month", "region", "agent_fte", "open_vacancies", "attrition_rate_12m"]].rename(
        columns={"month": "month_opened"})

    df = (c.merge(sys_cols, on="source_system", how="left")
           .merge(meter_cols, on=["month_opened", "region"], how="left")
           .merge(staff_cols, on=["month_opened", "region"], how="left"))
    df["source_system_age_years"] = 2026 - df["source_system_year"]
    df["category_group"] = df["category"].str.split(" - ").str[0]
    df["estimate_driven"] = df["category"].isin(ESTIMATE_DRIVEN).astype(int)
    df["smart_region"] = (df["region_systems"].str.contains("SYS-07")).astype(int)
    # Plan: $121 if transferred, else the $68 average (northwind_unit_costs.csv).
    df["handling_unit_cost"] = df["transferred_between_systems"].map(
        {1: u["complaint_transferred"], 0: u["complaint_avg"]})
    df["is_open"] = df["date_closed"].isna().astype(int)
    return df


def build_region_month(cx: pd.DataFrame, con) -> pd.DataFrame:
    opened = cx.groupby(["region", "month_opened"]).agg(
        complaints_opened=("complaint_id", "size"),
        transfers=("transferred_between_systems", "sum"),
        breaches=("sla_breach", "sum"),
        reopened=("reopened", "sum"),
    ).reset_index().rename(columns={"month_opened": "month"})
    closed = cx[cx["is_open"] == 0].groupby(["region", "month_closed"]).agg(
        complaints_closed=("complaint_id", "size"),
        avg_days_to_close=("days_to_close", "mean"),
    ).reset_index().rename(columns={"month_closed": "month"})
    m = read(con, "meter_reads")[["month", "region", "estimated_read_rate",
                                   "smart_meter_penetration", "billing_exceptions_raised"]]
    st = read(con, "staffing")[["month", "region", "agent_fte"]]
    rm = opened.merge(closed, on=["region", "month"], how="left").merge(m, on=["region", "month"]) \
               .merge(st, on=["region", "month"])
    rm["transfer_rate"] = rm["transfers"] / rm["complaints_opened"]
    rm["breach_rate"] = rm["breaches"] / rm["complaints_opened"]
    return rm.sort_values(["region", "month"]).reset_index(drop=True)


def build_segment_summary(cx: pd.DataFrame) -> pd.DataFrame:
    seg = cx.copy()
    seg["information_only"] = seg["resolvable_by_information_only"].map({1: "yes", 0: "no"}).fillna("open")
    seg["bill_correction"] = seg["resolution_action"].isin(CORRECTION_ACTIONS).astype(int)
    out = seg.groupby(["category", "transferred_between_systems", "information_only"]).agg(
        complaints=("complaint_id", "size"),
        avg_days_to_close=("days_to_close", "mean"),
        breach_rate=("sla_breach", "mean"),
        reopen_rate=("reopened", "mean"),
        total_handling_cost=("handling_unit_cost", "sum"),
        bill_corrections=("bill_correction", "sum"),
        bill_correction_value=("bill_correction_value", "sum"),
    ).reset_index()
    return out.rename(columns={"transferred_between_systems": "transferred"})


def build_backlog_month(con) -> pd.DataFrame:
    """Month-level KPI series plus the open backlog reconstructed from the complaints file.

    backlog at a date = complaints opened on/before it and not yet closed.
    Used for the queue view in the scenario engine (days to close tracks backlog).
    """
    c = read(con, "complaints")
    k = read(con, "monthly_kpis")
    opened = pd.to_datetime(c["date_opened"])
    closed = pd.to_datetime(c["date_closed"])
    rows = []
    for month in k["month"]:
        start = pd.Timestamp(month + "-01")
        end = start + pd.offsets.MonthEnd(0)
        b_start = int(((opened < start) & (closed.isna() | (closed >= start))).sum())
        b_end = int(((opened <= end) & (closed.isna() | (closed > end))).sum())
        in_month = c[c["month_closed"] == month]
        rows.append({
            "month": month,
            "backlog_start": b_start,
            "backlog_end": b_end,
            "avg_days_not_transferred": in_month.loc[in_month["transferred_between_systems"] == 0,
                                                     "days_to_close"].mean(),
            "avg_days_transferred": in_month.loc[in_month["transferred_between_systems"] == 1,
                                                 "days_to_close"].mean(),
        })
    b = k.merge(pd.DataFrame(rows), on="month")
    b["backlog_avg"] = (b["backlog_start"] + b["backlog_end"]) / 2
    return b


def build() -> None:
    con = connect()
    cx = build_complaint_360(con)
    tables = {
        "complaint_360": cx,
        "region_month": build_region_month(cx, con),
        "segment_summary": build_segment_summary(cx),
        "backlog_month": build_backlog_month(con),
    }
    EXPORTS.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_sql(name, con, if_exists="replace", index=False)
        df.to_csv(EXPORTS / f"{name}.csv", index=False)
    con.commit()
    con.close()
    print("built " + ", ".join(f"{k}={len(v)}" for k, v in tables.items()) + " -> data/exports/")


if __name__ == "__main__":
    build()
