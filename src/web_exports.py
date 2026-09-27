"""Static JSON for the landing page (web/home.html), served by the existing /static mount.

    python -m src.web_exports      (also runs in `python run.py data`)
Reads the region_month and complaint_360 tables; no new tables, no API change.
The data pack only tags water-network complaints ("Water - pressure or quality") as water;
everything else (billing, metering, supply, service) is counted as electricity.
"""
from __future__ import annotations

import json

import pandas as pd

from .config import WEB, connect

OUT = WEB / "static" / "data" / "regions.json"
WATER = "Water - pressure or quality"


def build() -> dict:
    con = connect()
    rm = pd.read_sql("SELECT * FROM region_month", con)
    cx = pd.read_sql("SELECT region, category, source_system, source_system_name, days_to_close, "
                     "transferred_between_systems AS t FROM complaint_360", con)
    con.close()

    last = rm["month"].max()
    water = cx.assign(w=cx["category"] == WATER).groupby("region")["w"].sum()
    regions = []
    for name, g in rm.groupby("region"):
        latest = g[g["month"] == last].iloc[0]
        total = int(g["complaints_opened"].sum())
        regions.append({
            "name": name,
            "complaints": total,
            "water": int(water[name]),
            "electricity": total - int(water[name]),
            "last_month": int(latest["complaints_opened"]),
            "smart_meter_penetration": float(latest["smart_meter_penetration"]),
            "estimated_read_rate": float(latest["estimated_read_rate"]),
            "transfer_rate": float(g["transfers"].sum() / total),
        })
    return {
        "period": f"{rm['month'].min()} to {last}",
        "total_complaints": int(sum(r["complaints"] for r in regions)),
        "transfer_share": float(cx["t"].mean()),
        "days_transferred": float(cx.loc[cx["t"] == 1, "days_to_close"].mean()),
        "days_not_transferred": float(cx.loc[cx["t"] == 0, "days_to_close"].mean()),
        "transfer_by_intake": {f"{k[0]} {k[1]}": float(v) for k, v in
                               cx.groupby(["source_system", "source_system_name"])["t"].mean().items()},
        "regions": regions,
        "source": "region_month + complaint_360 (northwind_complaints.csv, northwind_meter_reads.csv)",
    }


def export() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote web/static/data/regions.json ({len(data['regions'])} regions)")


if __name__ == "__main__":
    export()
