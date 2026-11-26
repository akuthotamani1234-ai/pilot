"""Phase 9: the application's feature inventory across runs (nothing found is forgotten; requirements linked through
test evidence) and the accountability of every imported requirement (coverage figures kept apart; a case that did not
run never counts as covered)."""
import json


import pytest

from backend import inventory
from tests.test_requirements_execution import _accept, api  # noqa: F401


def _run(tmp_path, name, features, cases=()):
    d = tmp_path / name
    d.mkdir()
    (d / "registry.json").write_text(json.dumps({"features": {f["id"]: f for f in features},
                                                 "pages": {"P-1": {"id": "P-1", "pattern": "/", "status": "inspected"}},
                                                 "counts": {"pages": {"sampled_out": 2, "not_reached": 1}}}))
    (d / "test_cases.json").write_text(json.dumps(list(cases)))
    return d


@pytest.fixture
def inv_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(inventory, "FOLDER", tmp_path / "inventory")
    return tmp_path


def test_the_inventory_keeps_every_feature_across_runs_with_its_coverage_and_requirements(inv_dir):
    cart = {"id": "F-CART", "level": "feature", "kind": "add_to_cart", "name": "add to cart", "pages": ["inventory"],
            "status": "verified", "tests": ["test_flows_ai.py::test_ai_flow_1"]}
    sort = {"id": "F-SORT", "level": "feature", "kind": "sort", "name": "sort products", "pages": ["inventory"],
            "status": "unresolved", "why": "no test was generated for it"}
    first = _run(inv_dir, "run1", [cart, sort], [{"requirement_test": "TC-QPL-4-1", "tests": ["test_ai_flow_1"]}])
    inv = inventory.merge("shop.example", first)
    assert inv["features"]["F-CART"]["coverage"] == "verified"
    assert inv["features"]["F-CART"]["requirements"] == ["TC-QPL-4-1"]  # (its test was that case's test)
    assert inv["features"]["F-SORT"]["coverage"] == "not tested" and "no test" in inv["features"]["F-SORT"]["why"]
    assert inv["summary"]["latest_run_limits"] == {"sampled_out": 2, "not_reached": 1}
    second = _run(inv_dir, "run2", [dict(sort, status="failed")])
    inv = inventory.merge("shop.example", second)
    assert inv["features"]["F-SORT"]["coverage"] == "failed" and inv["features"]["F-SORT"]["runs_seen"] == 2
    assert inv["features"]["F-CART"]["coverage"] == "not reached"  # (kept, never silently dropped)
    assert inv["features"]["F-CART"]["last_verified_run"] == "run1"
    assert inventory.load("shop.example")["summary"]["by_coverage"] == {"not reached": 1, "failed": 1}


def test_every_requirement_is_accounted_for_and_a_case_that_did_not_run_is_never_covered(api, monkeypatch):
    from backend.atlassian import bridge
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    acc = api.client.get("/api/requirements/accountability", headers=api.H).json()
    req = acc["requirements"][0]
    assert req["requirement"] == "QPL-2" and len(req["criteria"]) >= 2 and req["scenarios"]["approved"] == 2
    assert req["requirement_coverage"] == 0 and req["automation_coverage"] == 0  # (nothing ran yet)
    assert all(c["outcome"] in ("not run yet", "blocked") for c in req["test_cases"])
    db = bridge.connect()
    try:
        ex = bridge.plan(db, "local", ["TC-QPL-2-1"], "requirements", {"url": "https://shop.example/",
                                                                     "type": "web"})["execution"]
        run = api.tmp / "runx"
        run.mkdir()
        (run / "test_cases.json").write_text(json.dumps([{"requirement_test": "TC-QPL-2-1",
                                                          "execution_status": "Passed"}]))
        bridge.collect(db, "local", ex["id"], run)
    finally:
        db.close()
    acc = api.client.get("/api/requirements/accountability", headers=api.H).json()
    req = acc["requirements"][0]
    one = next(c for c in req["test_cases"] if c["id"] == "TC-QPL-2-1")
    assert one["outcome"] == "Passed" and one["engine"] == "Playwright (browser)"
    assert req["pass_rate"] == 100 and 0 < req["requirement_coverage"] < 100
    assert acc["summary"]["note"].startswith("Requirement coverage counts criteria with a PASSED test")


def test_the_inventory_route(inv_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import server
    inventory.merge("shop.example", _run(inv_dir, "run1", [{"id": "F-1", "name": "x", "status": "verified"}]))
    c = TestClient(server.app, base_url="http://127.0.0.1:8000")
    r = c.get("/api/inventory?host=shop.example", headers={"X-Agentic-QA": "1"}).json()
    assert r["features"][0]["id"] == "F-1" and r["summary"]["features"] == 1
    assert c.get("/api/inventory?host=../etc", headers={"X-Agentic-QA": "1"}).status_code == 400

