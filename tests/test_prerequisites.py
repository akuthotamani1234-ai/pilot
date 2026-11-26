"""Prerequisites between requirement test cases (backend/atlassian/prerequisites.py, bridge.plan / collect): from Jira
links and declared preconditions, a persistent graph; added to a run even when not selected; cycles never followed; a
test whose prerequisite failed is Blocked, naming it."""
import json

import pytest

from backend.atlassian import bridge, prerequisites as pq


def case(cid, req, title, kind="positive", pre=(), steps=("Do it",), expected="it works", status="approved", **kw):
    return {"id": cid, "tenant_id": "t", "requirement_id": req, "status": status, "fingerprint": cid, "version": 1,
            "kind": kind, "title": title, "preconditions": list(pre), "steps": list(steps), "expected": expected,
            "assertions": [], "test_data_needs": [], "source_key": f"jira:{req}", "source_version": 1,
            "criterion_ids": [f"{req}#AC-1"], **kw}


CART = case("TC-A-1", "A", "Add a product to the shopping cart", steps=["Open the product list", "Add a product"],
            expected="the shopping cart contains the product")
LOGIN = case("TC-L-1", "L", "Log in with a valid account", expected="the account page opens")
CHECKOUT = case("TC-B-1", "B", "Start checkout", pre=["the shopping cart contains a product"],
                steps=["Given the shopping cart contains a product", "Open the cart", "Start checkout"],
                expected="the checkout form opens")
LOGGED_IN = case("TC-C-1", "C", "See the profile", pre=["the user is logged in"], expected="the profile is shown")


def test_a_declared_precondition_is_matched_to_the_case_that_establishes_it_and_login_is_left_to_the_engine():
    edges = pq.infer([CART, LOGIN, CHECKOUT, LOGGED_IN], {})
    assert [(e["case_id"], e["requires_id"], e["source"]) for e in edges] == [("TC-B-1", "TC-A-1", "declared")]
    assert "the shopping cart contains a product" in edges[0]["reason"]


def test_a_jira_link_makes_every_case_of_the_story_need_the_linked_storys_positive_cases():
    neg = case("TC-A-2", "A", "Add nothing", kind="negative")
    sources = {"B": {"content": {"links": [{"key": "A", "type": "is blocked by"}, {"key": "Z", "type": "relates to"}]}}}
    edges = pq.infer([CART, neg, case("TC-B-2", "B", "Other")], sources)
    assert {(e["case_id"], e["requires_id"], e["source"]) for e in edges} == {("TC-B-2", "TC-A-1", "link")}
    assert "is blocked by A" in edges[0]["reason"]


def test_a_cycle_is_reported_and_never_followed():
    edges = [{"case_id": "X", "requires_id": "Y", "reason": "r"}, {"case_id": "Y", "requires_id": "X", "reason": "r"},
             {"case_id": "Z", "requires_id": "X", "reason": "r"}]
    assert pq.cycles(edges) and set(pq.cycles(edges)[0]) == {"X", "Y"}
    plan = pq.closure(["Z"], edges, {"X", "Y", "Z"})
    assert plan["added"] == ["X"] and plan["requires"] == {"Z": ["X"]} and plan["cycles"]


def test_a_prerequisite_that_cannot_run_is_listed_not_silently_dropped():
    edges = [{"case_id": "B", "requires_id": "A", "reason": "needs A"}]
    plan = pq.closure(["B"], edges, {"B"})
    assert plan["added"] == [] and plan["skipped"] == [{"case": "B", "requires": "A", "reason": "needs A"}]


def test_transitive_prerequisites_come_deepest_first():
    edges = [{"case_id": "C", "requires_id": "B", "reason": ""}, {"case_id": "B", "requires_id": "A", "reason": ""}]
    plan = pq.closure(["C"], edges, {"A", "B", "C"})
    assert plan["order"] == ["A", "B", "C"] and plan["added"] == ["A", "B"]
    assert pq.all_requirements_of("C", plan["requires"]) == ["A", "B"]


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "refresh", lambda *a, **k: None)  # (no imported stories here: nothing goes stale)
    d = bridge.connect(tmp_path / "req.db")
    for c in (CART, LOGIN, CHECKOUT, LOGGED_IN):
        bridge._save(d, "t", dict(c), "test")
    yield d
    d.close()


def test_a_run_adds_the_unselected_prerequisite_and_the_dependent_does_its_steps_first(db):
    graph = bridge.plan_dependencies(db, "t")
    assert [(e["case_id"], e["requires_id"]) for e in graph["edges"]] == [("TC-B-1", "TC-A-1")]
    planned = bridge.plan(db, "t", ["TC-B-1"], "requirements", {"url": "https://shop.example/"})
    ex = planned["execution"]
    assert ex["case_ids"] == ["TC-B-1", "TC-A-1"] and ex["prerequisites"]["added"] == ["TC-A-1"]
    tests = {t["tc"]: t for t in planned["requirement_tests"]}
    assert tests["TC-B-1"]["text"].startswith("Prerequisite (do first")
    assert "Add a product to the shopping cart: Open the product list; Add a product" in tests["TC-B-1"]["text"]
    assert tests["TC-A-1"]["prerequisite_for"] == ["TC-B-1"]


def test_a_person_can_remove_an_inferred_prerequisite_and_it_stays_removed(db):
    bridge.plan_dependencies(db, "t")
    pq.set_manual(db, "t", "TC-B-1", "TC-A-1", present=False)
    bridge.plan_dependencies(db, "t")  # (a later plan does not bring it back)
    assert bridge.dependency_graph(db, "t")["edges"] == []
    with pytest.raises(ValueError):
        pq.set_manual(db, "t", "TC-A-1", "TC-A-1", present=True)


def _run(tmp_path, statuses: dict[str, str]):
    d = tmp_path / "run"
    d.mkdir()
    cases = [{"requirement_test": tc, "execution_status": st, "tc_id": tc,
              "failure_category": "Assertion failure" if st == "Failed" else ""} for tc, st in statuses.items()]
    (d / "test_cases.json").write_text(json.dumps(cases))
    return d


def test_a_test_whose_prerequisite_failed_is_blocked_naming_it(db, tmp_path):
    bridge.plan_dependencies(db, "t")
    ex = bridge.plan(db, "t", ["TC-B-1"], "requirements", {"url": "https://shop.example/"})["execution"]
    done = bridge.collect(db, "t", ex["id"], _run(tmp_path, {"TC-A-1": "Failed", "TC-B-1": "Failed"}))
    res = {r["test_case_id"]: r for r in bridge.results(db, "t", ex["id"])}
    assert res["TC-B-1"]["status"] == "Blocked" and res["TC-B-1"]["blocked_by"] == "TC-A-1"
    assert "prerequisite TC-A-1 did not pass" in res["TC-B-1"]["reason"] and res["TC-B-1"]["own_status"] == "Failed"
    assert res["TC-A-1"]["status"] == "Failed" and res["TC-A-1"]["role"].startswith("prerequisite (added")
    assert bridge.outcome_of(done)["tally"]["prerequisites_added"] == 1


def test_a_test_that_passed_stays_passed_even_if_its_prerequisite_test_failed(db, tmp_path):
    bridge.plan_dependencies(db, "t")
    ex = bridge.plan(db, "t", ["TC-B-1"], "requirements", {"url": "https://shop.example/"})["execution"]
    bridge.collect(db, "t", ex["id"], _run(tmp_path, {"TC-A-1": "Failed", "TC-B-1": "Passed"}))
    res = {r["test_case_id"]: r for r in bridge.results(db, "t", ex["id"])}
    assert res["TC-B-1"]["status"] == "Passed"  # (it set the state up itself: its own result stands)


def test_ai_dependencies_keep_only_real_case_ids(monkeypatch):
    from backend import llm
    monkeypatch.setattr(llm, "llm_enabled", lambda: True)

    def answer(prompt, shape, **kw):
        item = shape.__args__[0]
        return [item(case="TC-B-1", requires="TC-A-1", reason="the cart must have a product"),
                item(case="TC-B-1", requires="TC-NOPE-9", reason="invented"),
                item(case="TC-A-1", requires="TC-A-1", reason="self")]
    monkeypatch.setattr(llm, "ask_structured", answer)
    edges, note = pq.ai_edges([CART, CHECKOUT])
    assert [(e["case_id"], e["requires_id"], e["source"]) for e in edges] == [("TC-B-1", "TC-A-1", "ai")]
    assert note == ""


# ================================================================ through the API, with a Jira link (mock Jira)
from tests.test_requirements_execution import api  # noqa: E402,F401
from tests.atlassian_mock import T0, adf, story  # noqa: E402


def test_running_one_story_adds_the_story_it_is_blocked_by_and_lists_the_graph(api, monkeypatch):
    from urllib.parse import quote
    from backend import requirements_api as rapi
    c, H = api.client, api.H
    api.mock.issues["QPL-5"] = story("QPL-5", "Checkout", T0, "", "")
    api.mock.issues["QPL-5"]["fields"]["description"] = adf("AC1: Starting checkout opens the checkout form")
    api.mock.issues["QPL-5"]["fields"]["issuelinks"] = [
        {"type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"}, "inwardIssue": {"key": "QPL-2"}}]
    rapi.JOBS.wait(c.post("/api/requirements/connections/jira-main/imports", headers=H,
                          json={"mode": "items", "keys": "QPL-5"}).json()["id"])
    for key in ("QPL-2", "QPL-5"):
        a = c.post(f"/api/requirements/items/jira-main/{key}/analyze", headers=H, json={}).json()["analysis"]
        for s in a["suggestions"]:
            if s["kind"] == "positive":
                c.post(f"/api/requirements/items/jira-main/{key}/suggestions/{quote(s['id'], safe='')}/review",
                       headers=H, json={"answer": "yes"})
        c.post(f"/api/requirements/items/jira-main/{key}/test-cases", headers=H)
    graph = c.post("/api/requirements/dependencies/plan", headers=H, json={}).json()
    assert {(e["case_id"], e["source"]) for e in graph["edges"]} >= {("TC-QPL-5-1", "link")}
    assert all(e["requires_id"].startswith("TC-QPL-2-") for e in graph["edges"] if e["case_id"] == "TC-QPL-5-1")
    launched = []
    monkeypatch.setattr(api.server, "_launch_run", lambda req, caller: launched.append(req) or {"id": 77})
    body = {"strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-5-1"]},
            "target": {"url": "https://shop.example/", "authorized": True, "test_username": "u", "test_password": "p"}}
    r = c.post("/api/requirements/executions", headers=H, json=body)
    assert r.status_code == 200, r.text
    ex = r.json()["execution"]
    assert ex["case_ids"][0] == "TC-QPL-5-1" and any(x.startswith("TC-QPL-2-") for x in ex["case_ids"][1:])
    assert ex["prerequisites"]["added"] and "QPL-2" in ex["requirements"]
    tests = {t["tc"]: t for t in launched[0].requirement_tests}
    assert tests["TC-QPL-5-1"]["text"].startswith("Prerequisite (do first")
    assert c.get("/api/requirements/dependencies", headers=H).json()["edges"]
