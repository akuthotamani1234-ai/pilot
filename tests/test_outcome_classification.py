"""Every selected Jira test case gets exactly one accurate outcome, and the kinds of 'not passed' stay apart:
an application defect (Failed), an automation error of the generated test (Requires review), a test that ran but
never established its expected result (Requires review, not Passed), a failed prerequisite (Blocked, naming it),
something the application does not offer (Not automated), and a case the run never produced (Not run)."""
import json

import pytest

from backend.atlassian import bridge
from tests.test_prerequisites import case

CASES = [case("TC-A-1", "A", "Add a product to the shopping cart", steps=["Add a product"],
              expected="the shopping cart contains the product"),
         case("TC-B-1", "B", "Start checkout", pre=["the shopping cart contains a product"],
              steps=["Given the shopping cart contains a product", "Start checkout"], expected="checkout opens"),
         case("TC-D-1", "D", "Sort by price", expected="cheapest first"),
         case("TC-E-1", "E", "Script error case", expected="x"),
         case("TC-F-1", "F", "Quoted result never checked", expected="'Thank you'"),
         case("TC-G-1", "G", "Coupons", expected="discount"),
         case("TC-H-1", "H", "Never produced", expected="y")]


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "refresh", lambda *a, **k: None)
    d = bridge.connect(tmp_path / "req.db")
    for c in CASES:
        bridge._save(d, "t", dict(c), "test")
    yield d
    d.close()


def test_each_selected_case_gets_one_accurate_and_separately_classified_outcome(db, tmp_path):
    bridge.plan_dependencies(db, "t")
    ids = ["TC-B-1", "TC-D-1", "TC-E-1", "TC-F-1", "TC-G-1", "TC-H-1"]
    ex = bridge.plan(db, "t", ids, "requirements", {"url": "https://shop.example/"})["execution"]
    assert "TC-A-1" in ex["case_ids"]  # (the prerequisite was added)
    run = tmp_path / "run"
    run.mkdir()
    rows = [
        {"requirement_test": "TC-A-1", "execution_status": "Failed", "failure_category": "Assertion failure",
         "actual_result": "the cart stayed empty"},                                   # application defect
        {"requirement_test": "TC-B-1", "execution_status": "Failed", "failure_category": "Assertion failure"},
        {"requirement_test": "TC-D-1", "execution_status": "Failed", "failure_category": "Assertion failure",
         "actual_result": "expected $7.99 first, got $29.99"},                        # application defect
        {"requirement_test": "TC-E-1", "execution_status": "Failed", "failure_category": "Test mistake",
         "actual_result": "ValueError: Unsupported type"},                             # automation error
        {"requirement_test": "TC-F-1", "execution_status": "Inconclusive",
         "actual_result": "the expected result its test case quotes was never checked: 'Thank you'"},
        {"requirement_test": "TC-G-1", "execution_status": "Not run",
         "skip_reason": "Not automated: the site has no coupon field"}]
    (run / "test_cases.json").write_text(json.dumps(rows))
    done = bridge.collect(db, "t", ex["id"], run)
    res = {r["test_case_id"]: r for r in bridge.results(db, "t", ex["id"])}
    assert set(res) == set(ex["case_ids"])  # (every selected case, and the added prerequisite, has an outcome)
    got = {k: v["status"] for k, v in res.items()}
    assert got == {"TC-A-1": "Failed", "TC-B-1": "Blocked", "TC-D-1": "Failed", "TC-E-1": "Requires review",
                   "TC-F-1": "Requires review", "TC-G-1": "Not automated", "TC-H-1": "Not run"}
    assert res["TC-B-1"]["blocked_by"] == "TC-A-1"
    assert res["TC-F-1"]["reason"].startswith("Inconclusive: the expected result")
    assert res["TC-E-1"]["failure_category"] == "Test mistake"
    t = bridge.outcome_of(done)["tally"]
    assert (t["passed"], t["failed"], t["requires_review"], t["blocked"], t["not_automated"], t["not_run"]) == \
        (0, 2, 2, 1, 1, 1)
