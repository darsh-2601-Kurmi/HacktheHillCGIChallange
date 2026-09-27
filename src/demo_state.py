"""Demo state that travels with the browser, for serverless hosting (Vercel).

On Vercel each request can land on a different instance, and each instance has its own /tmp copy of the database,
so a case created on one instance is unknown to the next. Here the OneCase demo state (cases, their events, bill
corrections) rides along instead: every API response carries it in the X-OneCase-State header, the page sends it
back with its next request, and the instance restores it before handling that request. Each visitor therefore has
their own demo, and a visitor with no state starts clean.

Active only when ENABLED (the VERCEL environment variable is set); local runs keep the single shared database.
"""
from __future__ import annotations

import base64
import json
import os
import zlib

HEADER = "X-OneCase-State"
ENABLED = bool(os.environ.get("VERCEL"))
TABLES = ("cases", "case_events", "bill_adjustments")
MAX_CASES = 6                       # about 1.4 KB each: keeps the header well under request-header limits


def _columns(con, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def dump(con) -> str:
    """The current demo state as a compact, URL-safe token (the most recent MAX_CASES cases)."""
    keep = [r[0] for r in con.execute(
        "SELECT case_id FROM cases ORDER BY CAST(SUBSTR(case_id, 4) AS INTEGER) DESC LIMIT ?", (MAX_CASES,))]
    marks = ",".join("?" * len(keep)) or "NULL"
    state = {}
    for t in TABLES:
        cols = _columns(con, t)
        rows = con.execute(f"SELECT {', '.join(cols)} FROM {t} WHERE case_id IN ({marks})", keep).fetchall()
        state[t] = [cols, [list(r) for r in rows]]
    raw = json.dumps(state, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode()


def load(con, token: str | None) -> None:
    """Replace the instance's demo tables with the state in token (clean state if absent or unreadable)."""
    try:
        state = json.loads(zlib.decompress(base64.urlsafe_b64decode(token.encode()))) if token else {}
    except (ValueError, zlib.error, AttributeError):
        state = {}
    for t in TABLES:
        con.execute(f"DELETE FROM {t}")
        allowed = set(_columns(con, t))
        cols, rows = (state.get(t) or [[], []])
        cols = [c for c in cols if c in allowed]            # never trust column names from the client
        if cols and rows:
            con.executemany(f"INSERT OR REPLACE INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [r[:len(cols)] for r in rows if isinstance(r, list)])
    con.commit()
