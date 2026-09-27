"""Diagnosis report (docs/report.html): every headline number, and the file is self-contained."""
import json
import re

import pytest

from src import report, svgchart


@pytest.fixture(scope="module")
def F():
    return report.facts()


@pytest.fixture(scope="module")
def page(F):
    return report.render(F)


def test_volume_and_transfers(F):
    assert (F["complaints"], F["open"], F["transferred"]) == (25_416, 1_599, 8_870)
    assert F["transfer_rate"] == pytest.approx(0.349, abs=5e-4)
    t, nt = F["cmp"]["t"], F["cmp"]["nt"]
    assert (round(t["days"], 1), round(nt["days"], 1)) == (38.2, 23.0)
    assert (round(t["breach"], 3), round(nt["breach"], 3)) == (0.887, 0.704)
    assert (round(t["reopen"], 3), round(nt["reopen"], 3)) == (0.269, 0.084)
    assert (t["cost"], nt["cost"]) == (121, 68)


def test_intake_system_explains_transfers(F):
    rates = {r["sys"]: r["rate"] for r in F["intake"]}
    assert rates.pop("SYS-04") == 0
    assert all(0.45 <= v <= 0.475 for v in rates.values())
    assert 0.32 <= F["flat_lo"] and F["flat_hi"] <= 0.375          # every other split stays flat
    assert "lose their history" in F["casetrack_note"]


def test_score_model(F):
    s = F["score"]
    assert s["slope"] == pytest.approx(-0.0691, abs=1e-4)
    assert s["intercept"] == pytest.approx(5.316, abs=1e-3)
    assert round(s["r"], 2) == -0.98 and round(s["days_for_4"], 1) == 19.0
    assert s["fell_every_month"] and (s["score"][0], s["score"][-1]) == (4.30, 2.58)


def test_billing_answers_and_calderfield(F):
    m = F["meters"]
    assert (round(m["pen"][0], 2), round(m["pen"][-1], 2)) == (0.30, 0.81)
    assert (round(m["est"][0], 2), round(m["est"][-1], 2)) == (0.21, 0.23)
    assert round(F["bill_meter_share"], 2) == 0.63 and round(F["billing_fixed"], 2) == 0.59
    io = F["info"]
    assert io["n"] == 5_865 and round(io["share"], 3) == 0.231 and round(io["days"], 1) == 28.0
    cal = F["staff"]["agents"]["Calderfield"]
    assert (cal[0], cal[-1]) == (73, 37)
    days = [v["days"] for v in F["staff"]["since"].values()]
    assert 33.4 <= min(days) and max(days) <= 34.9


def test_scenarios_and_what_if(F):
    S = F["scen"]
    assert (round(S["recommended"]["m12_static"], 2), round(S["recommended"]["m12_queue"], 2)) == (3.23, 4.76)
    assert S["recommended"]["reach_queue"] == 5 and S["recommended"]["reach_static"] is None
    assert max(s["m12_static"] for s in S.values()) == pytest.approx(3.41, abs=5e-3)
    assert S["status_quo"]["reach_queue"] is None
    rows = F["grid"]["rows"]
    assert len(rows) == 375
    assert rows["0|0|0|0"][:2] == pytest.approx([2.68, 1.93], abs=5e-3) and rows["0|0|0|0"][3:] == [2271, 0]
    assert rows["100|50|50|0"] == pytest.approx([3.23, 4.76, 30.3, 231, 525_342], abs=5e-3)
    assert rows["100|100|100|35"][0] == pytest.approx(3.41, abs=5e-3) and rows["100|100|100|35"][4] == 754_461


def test_page_is_self_contained(page):
    assert page.count('class="page"') == 9
    assert not re.search(r"https?://", page), "the report must not reference anything online"
    assert "<link" not in page and "<script src" not in page and "url(" not in page
    assert "NaN" not in page and not re.search(r'[=,\s]-?(nan|inf)[",\s]', page)   # no broken coordinates
    data = json.loads(page.split('id="whatif-data">', 1)[1].split("</script>", 1)[0])
    assert len(data["rows"]) == 375 and data["today"] == 2.58


def test_build_writes_file(tmp_path):
    out = tmp_path / "report.html"
    report.build(out)
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_nice_ticks():
    assert svgchart.nice(2.58, 4.3) == (2.5, 4.5, [2.5, 3.0, 3.5, 4.0, 4.5])
    assert svgchart.nice(9.1, 38.2, zero=True) == (0, 40, [0, 10, 20, 30, 40])
    assert svgchart.fixed(1, 5, 4) == (1, 5, [1, 2, 3, 4, 5])
