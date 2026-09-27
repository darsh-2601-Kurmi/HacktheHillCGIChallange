"""API smoke tests: the demo path works end to end over HTTP."""
import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.synth_accounts import DEMO


@pytest.fixture
def client(isolated_db):
    c = TestClient(app)
    c.post("/reset")
    return c


def test_health_and_meta(client):
    assert client.get("/health").json()["status"] == "ok"
    m = client.get("/meta").json()
    assert [d["label"] for d in m["demo"]] == list("ABCDE")
    assert m["baseline"]["days_transferred"] == 38.2 and m["baseline"]["days_not_transferred"] == 23.0


def test_demo_path_A_then_D(client):
    meta = {d["label"]: d for d in client.get("/meta").json()["demo"]}
    a = client.post("/intake", json={"account_id": meta["A"]["account_id"], **meta["A"]["intake"]}).json()
    assert a["owning_team"] == "Billing resolution" and a["bill_check"]["difference_dollars"] == 171.08
    done = client.post(f"/cases/{a['case_id']}/actions", json={"action": "correct_bill"}).json()
    assert done["status"] == "Resolved"
    legacy = client.get(f"/legacy-path/{a['case_id']}").json()
    assert [h["system_id"] for h in legacy["hops"]][:2] == ["SYS-05", "SYS-04"]
    assert legacy["stats"]["transfer_probability"] == pytest.approx(0.456, abs=0.001)
    assert legacy["onecase"]["transfers"] == 0

    d = client.post("/intake", json={"account_id": meta["D"]["account_id"], **meta["D"]["intake"]}).json()
    assert d["owning_team"] == "Network"
    d2 = client.post(f"/cases/{d['case_id']}/actions", json={"action": "reassign", "team": "Billing resolution"}).json()
    assert d2["case_id"] == d["case_id"] and d2["owning_team"] == "Billing resolution"


def test_account_panel(client):
    acc = client.get(f"/accounts/{DEMO['A']['account_id']}").json()
    assert len(acc["months"]) == 12 and acc["account"]["meter_type"] == "smart"
    assert len(acc["past_complaints"]) == 1
    assert client.get("/accounts/ACC-NOPE").status_code == 404


def test_bad_requests(client):
    assert client.post("/intake", json={"account_id": "ACC-NOPE", "channel": "Phone", "category": "Other"}).status_code == 404
    assert client.post("/intake", json={"account_id": DEMO["E"]["account_id"], "channel": "Pigeon",
                                        "category": "Other"}).status_code == 400
    assert client.get("/cases/OC-99999").status_code == 404


def test_customer_check_creates_then_links(client):
    aid = DEMO["A"]["account_id"]
    first = client.post("/customer/check", json={"account_id": aid}).json()
    assert first["case"] and not first["linked_existing"]
    second = client.post("/customer/check", json={"account_id": aid}).json()
    assert second["linked_existing"] and second["case"]["case_id"] == first["case"]["case_id"]
    clean = client.post("/customer/check", json={"account_id": DEMO["E"]["account_id"]}).json()
    assert clean["case"] is None and clean["check"]["outcome"] == "bill_verified"


def test_scenarios(client):
    s = client.get("/scenario", params={"transfers": 1}).json()
    assert len(s["months"]) == 12 and s["summary"]["static"]["score_month12"] == pytest.approx(3.0, abs=0.1)
    named = client.get("/scenarios").json()
    assert len(named["scenarios"]) == 5


def test_pages_served(client):
    for p in ["/", "/home", "/desk", "/impact", "/customer", "/static/data/regions.json",
              "/static/vendor/three.module.js", "/static/vendor/three.core.js"]:
        assert client.get(p).status_code == 200
    assert client.get("/").text == client.get("/home").text          # the site opens on the landing page
    assert "OneCase agent desk" in client.get("/desk").text
