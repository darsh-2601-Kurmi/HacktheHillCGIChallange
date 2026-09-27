"""Hosted demo: the case state travels with the browser, so a request that lands on a fresh instance still works."""
import pytest
from fastapi.testclient import TestClient

from src import cases, demo_state
from src.api import app
from src.config import connect
from src.synth_accounts import DEMO

H = demo_state.HEADER


@pytest.fixture
def hosted(isolated_db, monkeypatch):
    monkeypatch.setattr(demo_state, "ENABLED", True)
    return TestClient(app)


def fresh_instance():
    """Another serverless instance: its own database copy, with none of this visitor's cases."""
    con = connect()
    cases.reset(con)
    con.close()


def test_case_survives_a_fresh_instance(hosted):
    meta = {d["label"]: d for d in hosted.get("/meta").json()["demo"]}
    r = hosted.post("/intake", json={"account_id": meta["B"]["account_id"], **meta["B"]["intake"]})
    case_id, token = r.json()["case_id"], r.headers[H]

    fresh_instance()
    assert hosted.post(f"/cases/{case_id}/actions", json={"action": "book_visit"}).status_code == 404   # the old bug

    fresh_instance()
    r = hosted.post(f"/cases/{case_id}/actions", json={"action": "book_visit"}, headers={H: token})
    assert r.status_code == 200 and r.json()["case_id"] == case_id
    fresh_instance()
    events = hosted.get(f"/cases/{case_id}", headers={H: r.headers[H]}).json()["timeline"]
    assert any("Meter read booked" in e["summary"] for e in events)


def test_bill_correction_travels_too(hosted):
    meta = {d["label"]: d for d in hosted.get("/meta").json()["demo"]}
    a = hosted.post("/intake", json={"account_id": meta["A"]["account_id"], **meta["A"]["intake"]})
    done = hosted.post(f"/cases/{a.json()['case_id']}/actions", json={"action": "correct_bill"}, headers={H: a.headers[H]})
    assert done.json()["status"] == "Resolved"
    fresh_instance()
    acct = hosted.get(f"/accounts/{DEMO['A']['account_id']}", headers={H: done.headers[H]}).json()
    assert any(m["corrected"] for m in acct["months"])


def test_no_state_means_a_clean_demo_and_bad_tokens_are_ignored(hosted):
    meta = {d["label"]: d for d in hosted.get("/meta").json()["demo"]}
    hosted.post("/intake", json={"account_id": meta["C"]["account_id"], **meta["C"]["intake"]})
    assert hosted.get("/cases").json() == [] or hosted.get("/cases").json().get("cases") == []
    assert hosted.get("/cases", headers={H: "not-a-token"}).status_code == 200
