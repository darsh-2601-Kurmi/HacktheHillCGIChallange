"""Paths and shared helpers. Every other module imports from here."""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
SYNTH = DATA / "synthetic"
EXPORTS = DATA / "exports"
if os.environ.get("NORTHWIND_DB"):                                    # tests point this at a copy
    DB_PATH = Path(os.environ["NORTHWIND_DB"])
elif os.environ.get("VERCEL"):      # read-only deploy: demo writes go to a /tmp copy, reset on each cold start
    DB_PATH = Path(tempfile.gettempdir()) / "northwind.db"
    if not DB_PATH.exists():
        shutil.copyfile(DATA / "northwind.db", DB_PATH)
else:
    DB_PATH = DATA / "northwind.db"
ASSUMPTIONS_PATH = ROOT / "assumptions.yaml"
ROUTING_RULES_PATH = DATA / "routing_rules.csv"
WEB = ROOT / "web"
DOCS = ROOT / "docs"

RAW_FILES = {
    "complaints": "northwind_complaints.csv",
    "systems": "northwind_systems.csv",
    "meter_reads": "northwind_meter_reads.csv",
    "monthly_kpis": "northwind_monthly_kpis.csv",
    "unit_costs": "northwind_unit_costs.csv",
    "ai_pilot": "northwind_ai_pilot_2025.csv",
    "staffing": "northwind_contact_centre_staffing.csv",
}

SMART_REGIONS = ["Ashford", "Calderfield", "Eastmarch", "Fenwick"]
NON_SMART_REGIONS = ["Barrowdale", "Dunmoor"]
REGIONS = sorted(SMART_REGIONS + NON_SMART_REGIONS)


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def load_assumptions(path: Path | str = ASSUMPTIONS_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def val(node):
    """Assumption entries are either a bare value or {value: x, source: ...}."""
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node
