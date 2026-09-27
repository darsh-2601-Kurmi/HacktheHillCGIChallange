"""Phase 4: OneCase API. Serves the web pages too, so one process runs the whole demo.

    uvicorn src.api:app --port 8000      (or: python run.py)
    Docs at http://localhost:8000/docs
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import billcheck, cases, demo_state, legacy, routing, scenario
from .config import DB_PATH, WEB, connect, load_assumptions, val
from .synth_accounts import DEMO

app = FastAPI(title="Northwind OneCase", version="1.0",
              description="One intake, one case, one screen. All account-level data is SYNTHETIC.")


@contextmanager
def db():
    con = connect()
    try:
        yield con
    finally:
        con.close()


# On Vercel the demo state travels with the browser (see demo_state.py); one request at a time per instance.
STATEFUL = ("/reset", "/intake", "/cases", "/legacy-path", "/accounts", "/billcheck", "/customer/check")
_state_lock = asyncio.Lock()


@app.middleware("http")
async def revalidate_pages(request: Request, call_next):
    """Pages, CSS and JS: browsers must check for a newer version (a cheap 304 when unchanged), so a redeploy is
    seen at once instead of an old cached stylesheet or script."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path in ("/", "/home", "/desk", "/impact", "/customer"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.middleware("http")
async def carry_demo_state(request: Request, call_next):
    if not demo_state.ENABLED or not request.url.path.startswith(STATEFUL):
        return await call_next(request)
    async with _state_lock:
        with db() as con:
            cases.ensure_schema(con)
            demo_state.load(con, request.headers.get(demo_state.HEADER))
        response = await call_next(request)
        with db() as con:
            response.headers[demo_state.HEADER] = demo_state.dump(con)
    return response


# --------------------------------------------------------------------------- models
class Intake(BaseModel):
    channel: str = Field(examples=["Phone"])
    account_id: str = Field(examples=["ACC-715270"])
    category: str = Field(examples=["Billing - estimated read"])
    free_text: str = ""
    priority: str = "P3"


class Action(BaseModel):
    action: str = Field(description="correct_bill | book_visit | explain | hold_reminders | reassign | "
                                    "escalate | note | resolve")
    team: str | None = None
    note: str | None = None


class CustomerCheck(BaseModel):
    account_id: str


# Pre-fill payloads for the demo buttons (plan, phase 6).
DEMO_INTAKE = {
    "A": {"channel": "Phone", "category": "Billing - estimated read", "priority": "P3",
          "free_text": "My last three bills look far too high. I have a smart meter, so why am I being estimated?"},
    "B": {"channel": "Web form", "category": "Billing - estimated read", "priority": "P3",
          "free_text": "My bills have been estimates since June. Nobody has read my meter."},
    "C": {"channel": "Phone", "category": "Billing - disputed amount", "priority": "P3",
          "free_text": "Why is my September bill so much higher than the summer? Nothing has changed at home."},
    "D": {"channel": "Phone", "category": "Supply - interruption", "priority": "P2",
          "free_text": "Power has been off since yesterday and I have just received a payment reminder."},
    "E": {"channel": "Email", "category": "Billing - disputed amount", "priority": "P3",
          "free_text": "Please check my latest bill is right."},
}


def _err(e: Exception):
    raise HTTPException(status_code=404 if "not found" in str(e) else 400, detail=str(e))


# --------------------------------------------------------------------------- meta
@app.get("/health")
def health():
    with db() as con:
        n = con.execute("SELECT COUNT(*) FROM synth_accounts").fetchone()[0]
    return {"status": "ok", "db": DB_PATH.name, "synthetic_accounts": n}


@app.get("/meta")
def meta():
    a = load_assumptions()
    cal = scenario.get_calibration()
    t = cal.cells
    days_t = (t[(0, 1)]["days"] * t[(0, 1)]["share"] + t[(1, 1)]["days"] * t[(1, 1)]["share"]) / (
        t[(0, 1)]["share"] + t[(1, 1)]["share"])
    days_n = (t[(0, 0)]["days"] * t[(0, 0)]["share"] + t[(1, 0)]["days"] * t[(1, 0)]["share"]) / (
        t[(0, 0)]["share"] + t[(1, 0)]["share"])
    return {
        "synthetic_label": "Synthetic data: account reads, bills and customers are generated. "
                           "Complaint history and statistics are from the Northwind data pack.",
        "channels": cases.CHANNELS, "categories": cases.CATEGORIES, "priorities": cases.PRIORITIES,
        "teams": routing.TEAMS,
        "demo": [{"label": k, "account_id": v["account_id"], "region": v["region"], "story": v["story"],
                  "intake": DEMO_INTAKE[k]} for k, v in DEMO.items()],
        "baseline": {"avg_days_to_close": val(a["baseline"]["avg_days_to_close"]),
                     "regulator_score": val(a["baseline"]["regulator_score"]),
                     "target": val(a["score_model"]["target"]),
                     "days_transferred": round(days_t, 1), "days_not_transferred": round(days_n, 1),
                     "transfer_share": round(cal.transfer_share, 3)},
    }


@app.post("/reset")
def reset():
    with db() as con:
        return cases.reset(con)


# --------------------------------------------------------------------------- cases
@app.post("/intake")
def intake(body: Intake):
    with db() as con:
        try:
            return cases.create_case(con, body.channel, body.account_id.strip().upper(), body.category,
                                     body.free_text, body.priority)
        except cases.CaseError as e:
            _err(e)


@app.get("/cases")
def list_cases(limit: int = 20, account_id: str | None = None):
    with db() as con:
        return cases.list_cases(con, limit, account_id)


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    with db() as con:
        c = cases.get_case(con, case_id)
    if c is None:
        raise HTTPException(404, f"case {case_id} not found")
    return c


@app.post("/cases/{case_id}/actions")
def case_action(case_id: str, body: Action):
    with db() as con:
        try:
            return cases.act(con, case_id, body.action, body.team, body.note)
        except cases.CaseError as e:
            _err(e)


@app.get("/legacy-path/{case_id}")
def legacy_path(case_id: str):
    with db() as con:
        c = cases.get_case(con, case_id)
        if c is None:
            raise HTTPException(404, f"case {case_id} not found")
        return legacy.legacy_path(con, c)


# --------------------------------------------------------------------------- accounts
@app.get("/accounts")
def search_accounts(q: str = Query("", min_length=0), limit: int = 10):
    q = q.strip().upper()
    with db() as con:
        rows = con.execute("SELECT account_id, region, meter_type, demo_label FROM synth_accounts "
                           "WHERE account_id LIKE ? ORDER BY demo_label IS NULL, account_id LIMIT ?",
                           (f"%{q}%", limit)).fetchall()
    return [dict(r) for r in rows]


@app.get("/accounts/{account_id}")
def account(account_id: str):
    account_id = account_id.strip().upper()
    with db() as con:
        loaded = billcheck.load_account(con, account_id)
        if loaded is None:
            raise HTTPException(404, f"account {account_id} not found")
        acc, bills, reads, adj, outage = loaded
        eff = billcheck.effective_bills(bills, adj)
        by_period = {r["period"]: r for r in reads}
        months = [{
            "period": b["period"], "read_type": by_period[b["period"]]["read_type"],
            "read_kwh": by_period[b["period"]]["read_kwh"], "billed_kwh": b["billed_kwh"],
            "read_type_used": b["read_type_used"], "amount": b["amount"],
            "effective_kwh": b["effective_kwh"], "effective_amount": b["effective_amount"],
            "corrected": b["corrected"], "corrected_by": b.get("corrected_by"),
        } for b in eff[-billcheck.WINDOW:]]
        past = [dict(r) for r in con.execute(
            "SELECT complaint_id, date_opened, date_closed, status, channel, category, source_system, "
            "transferred_between_systems AS transferred, days_to_close, sla_breach, reopened, resolution_action "
            "FROM complaints WHERE account_id=? ORDER BY date_opened DESC", (account_id,))]
        onecase = cases.list_cases(con, 10, account_id)
    return {"account": acc, "outage": outage, "months": months, "past_complaints": past,
            "onecase_cases": onecase, "synthetic_data": True}


@app.get("/billcheck/{account_id}")
def bill_check(account_id: str):
    with db() as con:
        r = billcheck.check_account(con, account_id.strip().upper())
    if r is None:
        raise HTTPException(404, f"account {account_id} not found")
    return r


# --------------------------------------------------------------------------- customer page (phase 7)
@app.post("/customer/check")
def customer_check(body: CustomerCheck):
    """Self-service bill check. Always creates or links to the SAME OneCase case: no new silo."""
    aid = body.account_id.strip().upper()
    with db() as con:
        chk = billcheck.check_account(con, aid)
        if chk is None:
            raise HTTPException(404, f"account {aid} not found")
        cases.ensure_schema(con)
        open_case = con.execute("SELECT 1 FROM cases WHERE account_id=? AND status != 'Resolved'", (aid,)).fetchone()
        case = None
        if open_case or chk["outcome"] in ("estimate_with_smart_read", "repeated_estimates_no_smart"):
            # create_case links to the open case if there is one: never a second record
            case = cases.create_case(con, "Web form", aid, "Billing - estimated read",
                                     "Customer ran 'Check my bill' (self-service).",
                                     origin="customer page", actor="Customer")
    return {"check": chk, "case": case, "linked_existing": bool(case and case.get("linked_existing"))}


# --------------------------------------------------------------------------- scenarios (phase 2 / 8)
def _scenario_json(res: dict) -> dict:
    return {"levers": res["levers"], "summary": res["summary"],
            "months": res["months"].round(4).to_dict(orient="records"),
            **{k: res[k] for k in ("id", "name", "note") if k in res}}


@app.get("/scenario")
def get_scenario(transfers: float = 0, info: float = 0, estimates: float = 0, agents: float = 0):
    res = scenario.run({"transfers_removed": transfers, "info_only_first_contact": info,
                        "estimated_read_reduction": estimates, "calderfield_agents_restored": agents},
                       build_cost_keys=["onecase_build_cost", "billing_feedback_loop_cost"] if estimates else
                       (["onecase_build_cost"] if transfers or info else []),
                       run_cost_keys=["onecase_run_cost_year"] if (transfers or info or estimates) else [])
    return _scenario_json(res)


@app.get("/scenarios")
def get_scenarios():
    a = load_assumptions()
    return {"scenarios": [_scenario_json(s) for s in scenario.named_scenarios(a)],
            "levers": a["levers"],
            "baseline": {k: val(v) for k, v in a["baseline"].items()},
            "score_model": {k: val(v) for k, v in a["score_model"].items()},
            "calibration": scenario.get_calibration().rows()}


# --------------------------------------------------------------------------- pages
@app.get("/", include_in_schema=False)
@app.get("/home", include_in_schema=False)
def page_home():
    return FileResponse(WEB / "home.html")


@app.get("/desk", include_in_schema=False)
def page_desk():
    return FileResponse(WEB / "index.html")


@app.get("/impact", include_in_schema=False)
def page_impact():
    return FileResponse(WEB / "impact.html")


@app.get("/customer", include_in_schema=False)
def page_customer():
    return FileResponse(WEB / "customer.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(WEB / "static" / "favicon.ico")


app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
