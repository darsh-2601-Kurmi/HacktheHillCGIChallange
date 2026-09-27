"""Phase 3: SYNTHETIC account-level meter reads and bills (the data pack has none).

Run:  python -m src.synth_accounts
Everything here is generated, seeded (reproducible) and labelled synthetic.

Generation assumptions (also in README):
- One account per account_id in the complaints file (region = region of its latest complaint)
  plus 2,000 extra accounts ACC-S00001.. spread across regions by account count.
- Smart meter: drawn from the region's smart_meter_penetration in the month of the account's
  latest complaint (2026-09 for extras) and treated as present for the whole window.
- 13 monthly periods 2025-09..2026-09 (12 shown; the 13th allows a same-month-last-year check).
- Usage: lognormal base (~340 kWh/month) x seasonal curve peaking in January x 6% noise.
- A bill is estimated with probability = region-month estimated_read_rate. That applies to smart
  accounts too: this is the diagnosed defect, the smart read exists but never reaches billing.
- MeterHub estimates use a flat profile (no seasonality, "unchanged since 2012") with a +8% bias.
- Non-smart accounts get a catch-up bill at the next actual read. Smart accounts do not: billing
  never reconciles against the smart read, so the gap persists until someone corrects it.
- Complaint accounts with a bill_correction_value in the window get an over-bill of that size
  on the 2-3 bills up to the complaint month, marked corrected by that complaint (they were closed).
- Five hand-built demo accounts A-E (see DEMO) overwrite whatever was generated for them.
"""
from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

from .config import SYNTH, connect, load_assumptions, val

SEED = 20260926
N_EXTRA = 2000
PERIODS = [f"{y}-{m:02d}" for y, m in [(2025, 9), (2025, 10), (2025, 11), (2025, 12)]
           + [(2026, m) for m in range(1, 10)]]
EST_BIAS = 0.08

# Hand-picked demo accounts. A-D are real account_ids from the complaints file, chosen for their
# (real) past complaint; their meter and billing history below is synthetic.
DEMO = {
    "A": {"account_id": "ACC-715270", "region": "Ashford", "smart": True,
          "story": "Smart meter, billed on estimates for 3 months while smart reads exist: over-billed."},
    "B": {"account_id": "ACC-361183", "region": "Dunmoor", "smart": False,  # = _pick_demo_b()
          "story": "No smart meter, four estimated bills in a row: needs a meter read."},
    "C": {"account_id": "ACC-795813", "region": "Calderfield", "smart": True,
          "story": "'Why is my bill higher?': actual reads, normal seasonal rise. Explain at first contact."},
    "D": {"account_id": "ACC-646945", "region": "Fenwick", "smart": True,
          "story": "Phone call about an outage (was SYS-05, transferred). One case, reassigned with history."},
    "E": {"account_id": "ACC-S00001", "region": "Eastmarch", "smart": True,
          "story": "Clean account. The bill is right and the tool says so."},
}


def _pick_demo_b(c: pd.DataFrame) -> str:
    counts = c["account_id"].value_counts()
    d = c[(c["account_id"].map(counts) == 1) & (c["date_opened"] < "2025-10-01") & (c["region"] == "Dunmoor")
          & (c["category"] == "Metering - no read taken") & (c["resolution_action"] == "Meter visit required")
          & (c["transferred_between_systems"] == 1) & (c["days_to_close"] >= 30)]
    return d.sort_values("complaint_id")["account_id"].iloc[0]


def _days(period: str) -> int:
    y, m = map(int, period.split("-"))
    return calendar.monthrange(y, m)[1]


def generate(con=None) -> dict[str, pd.DataFrame]:
    a = load_assumptions()
    rate = val(a["synthetic_tariff"]["rate_per_kwh"])
    standing = val(a["synthetic_tariff"]["standing_charge_per_day"])
    rng = np.random.default_rng(SEED)
    own = con is None
    con = con or connect()
    c = pd.read_sql("SELECT * FROM complaints", con)
    meter = pd.read_sql("SELECT * FROM meter_reads", con)

    DEMO["B"]["account_id"] = DEMO["B"]["account_id"] or _pick_demo_b(c)

    # ---- accounts
    latest = c.sort_values("date_opened").groupby("account_id").tail(1)
    acc = latest[["account_id", "region", "month_opened"]].rename(columns={"month_opened": "draw_month"})
    acc["origin"] = "complaints file"
    last_month = meter[meter["month"] == "2026-09"]
    weights = last_month.set_index("region")["accounts"]
    extra = pd.DataFrame({
        "account_id": [f"ACC-S{i:05d}" for i in range(1, N_EXTRA + 1)],
        "region": rng.choice(weights.index, size=N_EXTRA, p=weights / weights.sum()),
        "draw_month": "2026-09", "origin": "synthetic extra"})
    acc = pd.concat([acc, extra], ignore_index=True).sort_values("account_id").reset_index(drop=True)
    pen = meter.set_index(["region", "month"])["smart_meter_penetration"]
    p_smart = pen.reindex(list(zip(acc["region"], acc["draw_month"]))).to_numpy()
    acc["has_smart_meter"] = (rng.random(len(acc)) < p_smart).astype(int)
    n, P = len(acc), len(PERIODS)

    # ---- usage and reads
    base = rng.lognormal(np.log(340), 0.35, n)
    amp = rng.uniform(0.2, 0.45, n)
    months = np.array([int(p[5:]) for p in PERIODS])
    season = 1 + amp[:, None] * np.cos(2 * np.pi * (months[None, :] - 1) / 12)
    true = np.maximum(30, np.round(base[:, None] * season * rng.normal(1, 0.06, (n, P))))
    est_rate = meter.set_index(["region", "month"])["estimated_read_rate"]
    rates = np.stack([est_rate.reindex(list(zip(acc["region"], [p] * n))).to_numpy() for p in PERIODS], axis=1)
    is_est = rng.random((n, P)) < rates
    estimate = np.round(base[:, None] * (1 + rng.normal(EST_BIAS, 0.10, (n, P))))
    smart = acc["has_smart_meter"].to_numpy().astype(bool)

    # ---- over-bills that match real bill_correction_value, on complaints inside the window
    forced_extra = np.zeros((n, P))
    corrected_by = np.full((n, P), None, dtype=object)
    idx = pd.Series(range(n), index=acc["account_id"])
    demo_ids = {d["account_id"] for d in DEMO.values()}
    bcv = c[c["bill_correction_value"].notna() & c["month_opened"].isin(PERIODS[1:])
            & ~c["account_id"].isin(demo_ids)]
    for row in bcv.itertuples():
        i, pc = idx[row.account_id], PERIODS.index(row.month_opened)
        k = min(2 if row.bill_correction_value <= 200 else 3, pc + 1)
        span = range(pc - k + 1, pc + 1)
        for p in span:
            is_est[i, p] = True
            forced_extra[i, p] = row.bill_correction_value / rate / k
            corrected_by[i, p] = row.complaint_id

    # ---- bills: walk the periods so non-smart accounts get catch-up bills
    billed = np.zeros((n, P))
    carry = np.zeros(n)  # unbilled kWh on non-smart accounts since their last actual read
    for p in range(P):
        forced = forced_extra[:, p] > 0
        est_now = is_est[:, p]
        b = np.where(forced, true[:, p] + forced_extra[:, p], np.where(est_now, estimate[:, p], true[:, p]))
        catch = (~smart) & (~est_now)
        b = np.where(catch, b + carry, b)
        carry = np.where(catch, 0.0, carry)
        carry = np.where((~smart) & est_now & ~forced, carry + (true[:, p] - b), carry)
        neg = b < 0
        carry = np.where(neg, b, carry)
        billed[:, p] = np.round(np.maximum(b, 0))

    reads = pd.DataFrame({
        "account_id": np.repeat(acc["account_id"].to_numpy(), P),
        "period": np.tile(PERIODS, n),
        "read_type": np.where(np.repeat(smart, P), "smart",
                              np.where(is_est.ravel(), "estimated", "manual")),
        "read_kwh": np.where(np.repeat(smart, P) | ~is_est.ravel(), true.ravel(), np.nan),
    })
    days = np.tile([_days(p) for p in PERIODS], n)
    corr = corrected_by.ravel()
    bills = pd.DataFrame({
        "account_id": reads["account_id"], "period": reads["period"],
        "billed_kwh": billed.ravel(),
        "read_type_used": np.where(is_est.ravel(), "estimated", "actual"),
        "days": days, "rate_per_kwh": rate, "standing_charge_per_day": standing,
    })
    bills["amount"] = (bills["billed_kwh"] * rate + days * standing).round(2)
    bills["corrected_kwh"] = np.where(corr != None, true.ravel(), np.nan)  # noqa: E711
    bills["corrected_amount"] = (bills["corrected_kwh"] * rate + days * standing).round(2)
    bills["corrected_by"] = corr

    acc["meter_type"] = np.where(acc["has_smart_meter"] == 1, "smart", "manual")
    acc["demo_label"] = None
    acc["display_name"] = None
    acc = acc.drop(columns=["draw_month"])

    accounts, reads, bills = _apply_demo(acc, reads, bills, rate, standing)
    for t in (accounts, reads, bills):
        t["synthetic"] = 1
    outages = pd.DataFrame([{"region": "Fenwick", "active": 1, "since": "2026-09-25 18:40",
                             "reference": "GW-OUT-2291", "note": "Placeholder outage flag (SYS-09 GridWatch)",
                             "synthetic": 1}])
    if own:
        con.close()
    return {"accounts": accounts, "reads": reads, "bills": bills, "outages": outages}


def _profile(kwh: list[int]) -> list[int]:
    assert len(kwh) == len(PERIODS)
    return kwh


# Hand-built 13-month histories (2025-09 .. 2026-09). None = no read taken.
def _demo_rows(label: str):
    if label == "A":  # smart; Jul-Sep 2026 billed on MeterHub estimates although smart reads exist
        use = _profile([318, 352, 401, 455, 489, 471, 430, 384, 341, 312, 296, 301, 322])
        billed = use[:10] + [use[10] + 190, use[11] + 205, use[12] + 216]  # over by 611 kWh = $171.08
        est = [False] * 10 + [True] * 3
        return use, use, billed, est
    if label == "B":  # manual meter, estimates since June 2026
        use = [335, 368, 420, 476, 512, 498, 452, 401, 360, None, None, None, None]
        billed = use[:9] + [380, 380, 380, 380]
        est = [False] * 9 + [True] * 4
        return use, use, billed, est
    if label == "C":  # smart, all actual; September up on summer, same as last September
        use = _profile([402, 436, 488, 552, 590, 571, 514, 452, 380, 318, 301, 322, 415])
        return use, use, use, [False] * 13
    if label == "D":  # smart, all actual, steady
        use = _profile([280, 305, 344, 392, 418, 406, 371, 330, 296, 268, 259, 262, 279])
        return use, use, use, [False] * 13
    if label == "E":  # smart, all actual, flat profile (gas heating)
        use = _profile([262, 268, 281, 297, 305, 301, 290, 276, 266, 255, 251, 254, 259])
        return use, use, use, [False] * 13
    raise KeyError(label)


def _apply_demo(acc, reads, bills, rate, standing):
    for label, spec in DEMO.items():
        aid = spec["account_id"]
        m = acc["account_id"] == aid
        if not m.any():
            raise ValueError(f"demo account {label} ({aid}) not generated")
        acc.loc[m, ["region", "has_smart_meter", "meter_type", "demo_label", "display_name"]] = [
            spec["region"], int(spec["smart"]), "smart" if spec["smart"] else "manual", label,
            f"Demo customer {label}"]
        use, read, billed, est = _demo_rows(label)
        rm, bm = reads["account_id"] == aid, bills["account_id"] == aid
        reads.loc[rm, "read_type"] = ["smart" if spec["smart"] else ("estimated" if e else "manual") for e in est]
        reads.loc[rm, "read_kwh"] = [np.nan if r is None else r for r in read]
        days = bills.loc[bm, "days"].to_numpy()
        bills.loc[bm, "billed_kwh"] = billed
        bills.loc[bm, "read_type_used"] = ["estimated" if e else "actual" for e in est]
        bills.loc[bm, "amount"] = (np.array(billed) * rate + days * standing).round(2)
        bills.loc[bm, ["corrected_kwh", "corrected_amount", "corrected_by"]] = [np.nan, np.nan, None]
    return acc, reads, bills


def build() -> None:
    con = connect()
    tables = generate(con)
    SYNTH.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_sql(f"synth_{name}", con, if_exists="replace", index=False)
        df.to_csv(SYNTH / f"synthetic_{name}.csv", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS ix_synth_reads_acc ON synth_reads(account_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_synth_bills_acc ON synth_bills(account_id)")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_synth_accounts ON synth_accounts(account_id)")
    con.commit()
    con.close()
    demo = ", ".join(f"{k}={v['account_id']}" for k, v in DEMO.items())
    print("synthetic " + ", ".join(f"{k}={len(v)}" for k, v in tables.items()) + f" | demo {demo}")


if __name__ == "__main__":
    build()
