"""Phase 1a: load the 7 raw CSVs into SQLite with correct types.

Run:  python -m src.load
Dates are stored as ISO text (YYYY-MM-DD, months as YYYY-MM), flags as integers.
Open cases keep NULL for date_closed, days_to_close and resolvable_by_information_only.
"""
from __future__ import annotations

import pandas as pd

from . import config
from .config import RAW, RAW_FILES, connect

# Short keys for unit_costs rows so code never matches on long item strings.
UNIT_COST_KEYS = {
    "Inbound call handled by agent": "call",
    "Complaint handled end to end (average)": "complaint_avg",
    "Complaint handled end to end (transferred between systems)": "complaint_transferred",
    "Manual bill correction and re-issue": "bill_correction",
    "Field meter visit": "field_visit",
    "Smart meter installation": "smart_meter_install",
    "Contact centre agent, fully loaded": "agent_fte_year",
    "Recruiting and onboarding a contact centre agent": "agent_hire",
    "AskNorthwind assistant pilot": "ai_pilot_year",
    "Regulator penalty, enhanced monitoring": "regulator_penalty_quarter",
    "Compensation payment, missed appointment or outage": "compensation",
}


def read_raw(name: str) -> pd.DataFrame:
    return pd.read_csv(RAW / RAW_FILES[name])


def typed_complaints() -> pd.DataFrame:
    c = read_raw("complaints")
    for col in ["date_opened", "date_closed"]:
        c[col] = pd.to_datetime(c[col]).dt.strftime("%Y-%m-%d")  # NaT -> NaN -> NULL
    c["month_opened"] = c["date_opened"].str[:7]
    c["month_closed"] = c["date_closed"].str[:7]
    for col in ["transferred_between_systems", "sla_days", "sla_breach", "reopened"]:
        c[col] = c[col].astype(int)
    for col in ["days_to_close", "resolvable_by_information_only"]:
        c[col] = c[col].astype("Int64")  # nullable: stays NULL on open cases
    return c


def typed_unit_costs() -> pd.DataFrame:
    u = read_raw("unit_costs")
    u.insert(0, "key", u["item"].map(UNIT_COST_KEYS))
    missing = u[u["key"].isna()]
    if len(missing):
        raise ValueError(f"Unknown unit cost rows: {missing['item'].tolist()}")
    return u


def build(db_path=None) -> None:
    tables = {
        "complaints": typed_complaints(),
        "systems": read_raw("systems"),
        "meter_reads": read_raw("meter_reads"),
        "monthly_kpis": read_raw("monthly_kpis"),
        "unit_costs": typed_unit_costs(),
        "ai_pilot": read_raw("ai_pilot"),
        "staffing": read_raw("staffing"),
    }
    con = connect(db_path)
    for name, df in tables.items():
        df.to_sql(name, con, if_exists="replace", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS ix_complaints_account ON complaints(account_id)")
    con.commit()
    con.close()
    print(f"loaded {len(tables)} raw tables into {(db_path or config.DB_PATH).name}: "
          + ", ".join(f"{k}={len(v)}" for k, v in tables.items()))


if __name__ == "__main__":
    build()
