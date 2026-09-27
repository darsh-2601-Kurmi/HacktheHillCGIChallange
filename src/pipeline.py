"""Rebuild everything derived from data/raw in one go (`python run.py data`)."""
from __future__ import annotations

import time

from . import cases, load, model360, report, scenario, synth_accounts, web_exports
from .config import connect


def build_all() -> None:
    t0 = time.time()
    load.build()             # phase 1: raw CSVs -> SQLite
    model360.build()         # phase 1: complaint_360, region_month, segment_summary, backlog_month
    synth_accounts.build()   # phase 3: synthetic accounts, reads, bills, outage flag
    scenario.get_calibration.cache_clear()
    scenario.export()        # phase 2: scenarios.csv, lever_grid.csv, calibration.csv
    web_exports.export()     # landing page: web/static/data/regions.json
    report.build()           # docs/report.html, the multi-page diagnosis report
    con = connect()
    cases.reset(con)         # phase 10: clean OneCase store
    con.close()
    print(f"data rebuilt in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    build_all()
