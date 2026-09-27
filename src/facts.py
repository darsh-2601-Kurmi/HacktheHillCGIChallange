"""Every headline number of the Northwind diagnosis, computed from the files as the pipeline writes them
(data/exports/*.csv plus the raw AI pilot file). Used by the Power BI project (src/pbip.py) for page titles and
text, and checked by tests/test_facts.py."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import EXPORTS, RAW, RAW_FILES, REGIONS, SMART_REGIONS

LEVERS = [("t", "transfers_removed", "Transfers removed", "OneCase: one case from intake to close, no re-keying"),
          ("i", "info_only_first_contact", "Answered at first contact", "Information-only complaints closed on the spot"),
          ("e", "estimated_read_reduction", "Estimate complaints avoided", "Bill on smart reads; fix estimates at source"),
          ("a", "calderfield_agents_restored", "Calderfield agents restored", "Rehire the agents Calderfield lost")]


def mlong(m: str) -> str:
    return pd.Period(m, "M").strftime("%b %Y")


def facts(exports=EXPORTS, raw=RAW) -> dict:
    """Every number the Power BI pages quote, computed from the files as loaded (no transforms on disk)."""
    c = pd.read_csv(exports / "complaint_360.csv", parse_dates=["date_opened"])
    rm = pd.read_csv(exports / "region_month.csv", dtype={"month": str})
    bm = pd.read_csv(exports / "backlog_month.csv", dtype={"month": str}).sort_values("month")
    scn = pd.read_csv(exports / "scenarios.csv", dtype={"month": str})
    lg = pd.read_csv(exports / "lever_grid.csv")
    cal = pd.read_csv(exports / "calibration.csv").set_index("name")["value"]
    ai = pd.read_csv(raw / RAW_FILES["ai_pilot"], dtype={"month": str}).sort_values("month")

    F: dict = {"rows": {"complaint_360": len(c), "region_month": len(rm), "backlog_month": len(bm),
                        "scenarios": len(scn), "lever_grid": len(lg), "calibration": len(cal), "ai_pilot": len(ai)}}
    t = c["transferred_between_systems"].eq(1)
    F["complaints"], F["open"], F["transferred"] = len(c), int(c["is_open"].sum()), int(t.sum())
    F["transfer_rate"] = float(t.mean())
    F["days_all"] = float(c["days_to_close"].mean())
    F["breach_all"] = float(c["sla_breach"].mean())
    F["handling_cost"] = float(c["handling_unit_cost"].sum())
    F["period"] = (mlong(bm["month"].iloc[0]), mlong(bm["month"].iloc[-1]))

    def grp(d):
        return {"n": len(d), "days": float(d["days_to_close"].mean()), "breach": float(d["sla_breach"].mean()),
                "reopen": float(d["reopened"].mean()), "cost": float(d["handling_unit_cost"].mean())}
    F["cmp"] = {"t": grp(c[t]), "nt": grp(c[~t])}

    it = (c.groupby(["source_system", "source_system_name"])["transferred_between_systems"].agg(["mean", "size"])
          .reset_index().sort_values("mean"))
    F["intake"] = [{"sys": r.source_system, "name": r.source_system_name, "rate": float(r["mean"]), "n": int(r["size"])}
                   for _, r in it.iterrows()]
    F["casetrack_note"] = c.loc[c["source_system"] == "SYS-04", "source_system_notes"].iloc[0]

    c["quarter"] = c["date_opened"].dt.year.astype(str) + " Q" + c["date_opened"].dt.quarter.astype(str)

    def rate_by(col, natural=False):
        g = c.groupby(col)["transferred_between_systems"].agg(["mean", "size"])
        g = g.sort_index() if natural else g.sort_values("size", ascending=False)
        return [{"label": k, "rate": float(r["mean"]), "n": int(r["size"])} for k, r in g.iterrows()]
    F["by"] = {"category": rate_by("category"), "channel": rate_by("channel"),
               "priority": rate_by("priority", True), "quarter": rate_by("quarter", True)}
    flat = [r["rate"] for rows in F["by"].values() for r in rows]
    F["flat_lo"], F["flat_hi"] = min(flat), max(flat)

    cat = (c.groupby("category").agg(n=("complaint_id", "size"), grp=("category_group", "first"))
           .sort_values("n", ascending=False))
    F["categories"] = [{"label": k, "n": int(r["n"]), "grp": r["grp"]} for k, r in cat.iterrows()]
    F["bill_meter_share"] = float(c["category_group"].isin(["Billing", "Metering"]).mean())
    F["estimate_driven"] = float(c["estimate_driven"].mean())
    bill = c[c["category_group"] == "Billing"]
    F["billing_fixed"] = float(bill["resolution_action"].isin(
        ["Bill corrected and re-issued", "Refund or credit applied"]).mean())

    io = c["resolvable_by_information_only"].eq(1)
    F["info"] = {"n": int(io.sum()), "share": float(io.sum() / len(c)),
                 "days": float(c.loc[io, "days_to_close"].mean()),
                 "transfer": float(c.loc[io, "transferred_between_systems"].mean())}

    x, y = bm["avg_days_to_close"], bm["regulator_satisfaction_score_of_5"]
    slope, intercept = np.polyfit(x, y, 1)
    F["score"] = {"months": bm["month"].tolist(), "score": y.tolist(), "days": x.tolist(),
                  "backlog": bm["backlog_end"].tolist(), "slope": float(slope), "intercept": float(intercept),
                  "r": float(np.corrcoef(x, y)[0, 1]), "days_for_4": float((4 - intercept) / slope),
                  "r_backlog": float(np.corrcoef(bm["backlog_avg"], x)[0, 1]),
                  "fell_every_month": bool((y.diff().dropna() < 0).all())}
    F["queue_slope"], F["queue_r"] = float(cal["queue_slope"]), float(cal["queue_fit_r"])

    sm = (rm[rm["region"].isin(SMART_REGIONS)].groupby("month")[["smart_meter_penetration", "estimated_read_rate"]]
          .mean().sort_index())
    last_m = rm["month"].max()
    latest = rm[rm["month"] == last_m].set_index("region")
    F["meters"] = {"months": sm.index.tolist(), "pen": sm["smart_meter_penetration"].tolist(),
                   "est": sm["estimated_read_rate"].tolist(),
                   "latest": sorted(({"region": r, "est": float(latest.loc[r, "estimated_read_rate"]),
                                      "pen": float(latest.loc[r, "smart_meter_penetration"])} for r in REGIONS),
                                    key=lambda d: -d["est"]),
                   "last_month": mlong(last_m)}

    ag = rm.pivot(index="month", columns="region", values="agent_fte").sort_index()
    since = c[c["date_opened"] >= "2026-03-01"].groupby("region").agg(
        days=("days_to_close", "mean"), breach=("sla_breach", "mean"), n=("complaint_id", "size"),
        transfer=("transferred_between_systems", "mean"))
    F["staff"] = {"months": ag.index.tolist(), "agents": {r: ag[r].tolist() for r in REGIONS},
                  "since": {r: {k: float(v) for k, v in since.loc[r].items()} for r in REGIONS}}

    F["ai"] = {k: ai[k].tolist() for k in ai.columns}

    S = {}
    for sid, g in scn.groupby("scenario_id", sort=False):
        g = g.sort_values("month_index")
        m12 = g[g["month_index"] == 12].iloc[0]

        def first(col):
            hit = g.loc[g[col] >= 4, "month_index"]
            return int(hit.min()) if len(hit) else None
        S[sid] = {"name": g["scenario_name"].iloc[0], "months": g["month"].tolist(),
                  "static": g["score_static"].tolist(), "queue": g["score_queue"].tolist(),
                  "m12_static": float(m12["score_static"]), "m12_queue": float(m12["score_queue"]),
                  "m12_days": float(m12["avg_days_static"]), "m12_backlog": float(m12["backlog"]),
                  "saving_year": float(m12["handling_saving"] * 12),
                  "reach_static": first("score_static"), "reach_queue": first("score_queue")}
    F["scen"] = S

    def key(r):
        return (f"{round(r.transfers_removed * 100)}|{round(r.info_only_first_contact * 100)}|"
                f"{round(r.estimated_read_reduction * 100)}|{int(r.calderfield_agents_restored)}")
    F["grid"] = {
        "rows": {key(r): [round(r.score_static_month12, 3), round(r.score_queue_month12, 3),
                          round(r.avg_days_month12, 2), round(r.backlog_month12), round(r.annual_saving_full_effect)]
                 for r in lg.itertuples()},
        "levels": {k: sorted({round(v * 100) if k != "a" else int(v) for v in lg[col]}) for k, col, _, _ in LEVERS},
    }
    return F
