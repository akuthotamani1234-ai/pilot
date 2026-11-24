"""Requirements Intelligence, Phase 4: approved scenarios -> stored test cases -> the EXISTING Qpilot run -> real
results per test case. The engine hook is tested through the real test-design agent (with a stub AI); the bridge
through the store; the API through the real server (its run launcher replaced only where a real run is not needed)."""
import json
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from backend import approvals, audit_store, objective as objective_mod, requirement_tests, requirements_api as rapi
from backend.agents import test_design
from backend.atlassian import analysis as an, bridge, credentials, jira, store
from backend.atlassian.models import Connection
from tests.atlassian_mock import EMAIL, T0, TOKEN, MockJira, adf, story

SITE = "https://acme-test.atlassian.net"
PAGES = [{"slug": "login", "url": "https://shop.test/", "title": "Login", "auth": False, "forms": [], "links": [],
          "buttons": [{"text": "Login", "selector": "#login-button"}],
          "inputs": [{"label": "Username", "selector": "#user-name", "type": "text"},
                     {"label": "Password", "selector": "#password", "type": "password"}]}]
REQ_TESTS = [{"id": "rq_tc_qpl_2_1", "text": "Log in with a valid account. Expected: the products page opens.",
              "tc": "TC-QPL-2-1", "requirement": "QPL-2", "criteria": ["QPL-2#AC-1"], "title": "Valid login"},
             {"id": "rq_tc_qpl_2_2", "text": "Delete the account. Expected: it is gone.", "tc": "TC-QPL-2-2",
              "requirement": "QPL-2", "criteria": ["QPL-2#AC-2"], "title": "Delete account"}]


# ================================================================ the engine hook (backend/requirement_tests.py)

def test_requirement_tests_are_read_for_this_run_only(monkeypatch):
    monkeypatch.setenv(requirement_tests.ENV, json.dumps(REQ_TESTS + [{"id": "bad id", "text": "x"},
                                                                     {"id": "rq_tc_qpl_2_1", "text": "duplicate"}]))
    loaded = requirement_tests.load()
    assert [t["id"] for t in loaded] == ["rq_tc_qpl_2_1", "rq_tc_qpl_2_2"] and loaded[0]["tc"] == "TC-QPL-2-1"
    assert requirement_tests.only() is False
    monkeypatch.setenv(requirement_tests.ONLY_ENV, "1")
    assert requirement_tests.only() is True
    monkeypatch.setenv(requirement_tests.ENV, "not json")
    assert requirement_tests.load() == [] and requirement_tests.only() is False


def test_requirement_tests_steer_the_objective_and_replace_saved_tests_when_only(tmp_path, monkeypatch):
    from backend import my_tests
    monkeypatch.setattr(my_tests, "load", lambda _site, **k: [{"id": "M1", "text": "My own saved test"}])
    monkeypatch.setenv(requirement_tests.ENV, json.dumps(REQ_TESTS[:1]))
    monkeypatch.setenv(requirement_tests.ONLY_ENV, "0")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    objective_mod.start(tmp_path / "a", "site", "", ai=True)
    assert [i["id"] for i in objective_mod.read(tmp_path / "a")["instructions"]] == ["M1", "rq_tc_qpl_2_1"]
    monkeypatch.setenv(requirement_tests.ONLY_ENV, "1")
    objective_mod.start(tmp_path / "b", "site", "", ai=True)
    assert [i["id"] for i in objective_mod.read(tmp_path / "b")["instructions"]] == ["rq_tc_qpl_2_1"]


def _stub_ai(prompt, model, **kw):
    return [test_design.AICase(title="Valid login", pages=["login"], test_data="the test account",
                               preconditions=["the login page is open"],
                               steps=["Type the test username in 'Username'", "Type the password in 'Password'",
                                      "Click 'Login'"], expected="the products page opens",
                               assertions=["the URL contains /inventory"])]


def test_requirement_based_design_writes_only_the_requirement_cases(tmp_path, monkeypatch):
    monkeypatch.setenv(requirement_tests.ENV, json.dumps(REQ_TESTS))
    monkeypatch.setenv(requirement_tests.ONLY_ENV, "1")
    monkeypatch.setattr(test_design, "llm_enabled", lambda: True)
    monkeypatch.setattr(test_design, "ask_structured", _stub_ai)
    objective_mod.start(tmp_path, "site", "", ai=True)
    out = test_design.test_design_agent({"app_map": [dict(p) for p in PAGES], "run_dir": str(tmp_path),
                                         "site_key": "shop.test", "url": "https://shop.test/"})
    cases = out["test_cases"]
    assert len(cases) == 2  # (no journeys, feature tests, site-wide checks: requirement-based only)
    by_tc = {c["requirement_test"]: c for c in cases}
    assert by_tc["TC-QPL-2-1"]["origin"] == "requirement" and by_tc["TC-QPL-2-1"]["feature"] == "Requirement QPL-2"
    assert by_tc["TC-QPL-2-1"]["requirement"] == "QPL-2 (AC-1)" and by_tc["TC-QPL-2-1"]["title"] == "Valid login"
    assert not by_tc["TC-QPL-2-1"].get("skip_reason") and by_tc["TC-QPL-2-1"]["steps"][-1] == "Click 'Login'"
    assert by_tc["TC-QPL-2-2"]["skip_reason"].startswith("Blocked: 'Delete'")  # (never done from an instruction)
    saved = json.loads((tmp_path / "test_cases.json").read_text())
    assert {c["requirement_test"] for c in saved} == {"TC-QPL-2-1", "TC-QPL-2-2"}


def test_hybrid_design_puts_requirement_cases_first_and_keeps_the_exploratory_suite(tmp_path, monkeypatch):
    monkeypatch.setenv(requirement_tests.ENV, json.dumps(REQ_TESTS[:1]))
    monkeypatch.setenv(requirement_tests.ONLY_ENV, "0")
    monkeypatch.setattr(test_design, "llm_enabled", lambda: False)
    out = test_design.test_design_agent({"app_map": [dict(p) for p in PAGES], "run_dir": str(tmp_path),
                                         "site_key": "shop.test", "url": "https://shop.test/"})
    cases = out["test_cases"]
    req = [c for c in cases if c.get("requirement_test")]
    assert len(req) == 1 and len(cases) > 1  # (plus the usual exploratory cases)
    assert req[0]["skip_reason"].startswith("Not automated: your own tests need an AI")  # (no AI: said, not faked)
    assert all(c.get("origin") != "requirement" for c in cases if not c.get("requirement_test"))


# ================================================================ the bridge (backend/atlassian/bridge.py)

def conn(tenant="t1"):
    return Connection(id="jira-main", tenant_id=tenant, product="jira", site_url=SITE, email=EMAIL,
                      token_ref="JIRA_READ_API_TOKEN")


@pytest.fixture
def db(tmp_path):
    d = bridge.connect(tmp_path / "req.sqlite")
    yield d
    d.close()


@pytest.fixture
def paths(tmp_path):
    return SimpleNamespace(approvals=tmp_path / "ap.sqlite", audit=tmp_path / "audit.sqlite")


def put_story(db, key="QPL-2", ac="AC1: A valid username and password open the products page\n"
                                  "AC2: A wrong password shows 'Username and password do not match'",
              when=T0, tenant="t1"):
    c = conn(tenant)
    store.save_connection(db, c)
    issue = story(key, "User Login Functionality", when, "", "")
    issue["fields"]["description"] = adf(*ac.split("\n"))
    item = jira.normalize(issue, c, retrieved_at=when)
    store.upsert_source(db, item["source"], item["story"])
    return f"jira-main:jira_issue:{key}"


def analysed(db, paths, key="QPL-2", accept=2, tenant="t1"):
    root = f"jira-main:jira_issue:{key}"
    a = an.analyze(db, tenant, root, approvals_db=paths.approvals, audit_db=paths.audit)
    for s in a.suggestions[:accept]:
        an.review(db, tenant, key, s.id, "yes", "alice", approvals_db=paths.approvals, audit_db=paths.audit)
    return store.get_analysis(db, tenant, key)


def test_only_accepted_scenarios_become_test_cases_with_their_sources(db, paths):
    put_story(db)
    a = analysed(db, paths, accept=1)
    out = bridge.generate(db, "t1", "QPL-2", audit_db=paths.audit)
    assert len(out["created"]) == 1 and out["created"][0] == "TC-QPL-2-1"
    c = bridge.get_case(db, "t1", "TC-QPL-2-1")
    accepted = next(s for s in a.suggestions if s.review.value == "accepted")
    assert c["suggestion_id"] == accepted.id and c["reviewer"] == "alice" and c["approval_id"] == accepted.approval_id
    assert c["source_key"] == "jira-main:jira_issue:QPL-2" and c["source_version"] == 1
    assert c["evidence"][0]["quote"] and c["evidence"][0]["locator"] == "description: acceptance criteria"
    assert c["status"] == "approved" and c["steps"] and c["expected"] and c["assertions"]
    assert "a test account (username and password)" in c["test_data_needs"]
    assert "Steps:" in bridge.instruction(c) and "Expected:" in bridge.instruction(c)


def test_generation_is_idempotent_and_versions_changes(db, paths):
    put_story(db)
    analysed(db, paths, accept=2)
    first = bridge.generate(db, "t1", "QPL-2")
    again = bridge.generate(db, "t1", "QPL-2")
    assert len(first["created"]) == 2 and again["created"] == [] and sorted(again["unchanged"]) == sorted(first["created"])
    assert len(bridge.list_cases(db, "t1")) == 2  # (no duplicates)


def test_a_changed_requirement_makes_test_cases_stale_and_refuses_generation_until_reanalysed(db, paths):
    put_story(db)
    analysed(db, paths)
    bridge.generate(db, "t1", "QPL-2")
    put_story(db, ac="AC1: A valid username and password open the products page within 2 seconds",
              when=T0 + timedelta(days=1))
    assert sorted(bridge.refresh(db, "t1")) == ["TC-QPL-2-1", "TC-QPL-2-2"]
    c = bridge.get_case(db, "t1", "TC-QPL-2-1")
    assert c["status"] == "stale" and "version 1 -> 2" in c["stale_reason"]
    assert [x["id"] for x in bridge.impacted(db, "t1")] == ["TC-QPL-2-1", "TC-QPL-2-2"]
    with pytest.raises(ValueError, match="analyse and review it again"):
        bridge.generate(db, "t1", "QPL-2")
    plan = None
    with pytest.raises(ValueError, match="no selected test case can run"):
        plan = bridge.plan(db, "t1", ["TC-QPL-2-1"], "requirements", {"url": "https://shop.test"})
    assert plan is None
    assert len(bridge.case_history(db, "t1", "TC-QPL-2-1")) == 2  # (generated, then stale: history kept)


def test_rejected_and_unreviewed_ideas_never_become_test_cases(db, paths):
    put_story(db)
    a = an.analyze(db, "t1", "jira-main:jira_issue:QPL-2", approvals_db=paths.approvals, audit_db=paths.audit)
    an.review(db, "t1", "QPL-2", a.suggestions[0].id, "no", "alice", approvals_db=paths.approvals,
              audit_db=paths.audit)
    out = bridge.generate(db, "t1", "QPL-2")
    assert out["created"] == [] and bridge.list_cases(db, "t1") == []


def test_editing_a_test_case_needs_a_new_approval(db, paths):
    put_story(db)
    analysed(db, paths, accept=1)
    bridge.generate(db, "t1", "QPL-2")
    c = bridge.edit_case(db, "t1", "TC-QPL-2-1", {"steps": ["Open the login page", "Log in as standard_user"]}, "bob")
    assert c["status"] == "awaiting_approval" and c["version"] == 2 and c["edited_by"] == "bob"
    assert c["source_key"].endswith("QPL-2")  # (the source link stays)
    with pytest.raises(ValueError, match="waiting for approval"):
        bridge.plan(db, "t1", ["TC-QPL-2-1"], "hybrid", {"url": "https://x"})
    approved = bridge.approve_case(db, "t1", "TC-QPL-2-1", "carol")
    assert approved["status"] == "approved" and approved["reviewer"] == "carol"


def test_results_come_only_from_the_runs_own_cases(db, paths, tmp_path):
    put_story(db)
    analysed(db, paths, accept=2)
    bridge.generate(db, "t1", "QPL-2")
    planned = bridge.plan(db, "t1", ["TC-QPL-2-1", "TC-QPL-2-2"], "requirements", {"url": "https://shop.test",
                                                                                    "test_password": "x"})
    ex = planned["execution"]
    assert "test_password" not in ex["target"] and len(planned["requirement_tests"]) == 2
    assert planned["requirement_tests"][0]["id"] == "rq_tc_qpl_2_1"
    bridge.attach_run(db, "t1", ex["id"], "7")
    run = tmp_path / "run"
    run.mkdir()
    (run / "test_cases.json").write_text(json.dumps([
        {"tc_id": "TC-001", "requirement_test": "TC-QPL-2-1", "execution_status": "Passed", "actual_result": "ok",
         "evidence": ["screenshots/1.png"], "check_count": 2},
        {"tc_id": "TC-002", "execution_status": "Failed"}]))  # (an exploratory case: not a requirement result)
    done = bridge.collect(db, "t1", ex["id"], run)
    assert done["counts"] == {"Passed": 1, "Not run": 1} and done["exploratory"] == {"cases": 1, "failed": 1,
                                                                                      "passed": 0}
    res = {r["test_case_id"]: r for r in bridge.results(db, "t1", ex["id"])}
    assert res["TC-QPL-2-1"]["status"] == "Passed" and res["TC-QPL-2-1"]["evidence"] == ["screenshots/1.png"]
    assert res["TC-QPL-2-1"]["case_version"] == 1 and res["TC-QPL-2-1"]["source_version"] == 1
    assert res["TC-QPL-2-2"]["status"] == "Not run"  # (never 'passed' without an executed case)
    cov = bridge.coverage(db, "t1")
    assert cov["with_test_cases"] == 1 and cov["executed"] == 1 and cov["passed"] == 0  # (one of two passed)
    rows = {(r["criterion"], r["test_case"]): r for r in bridge.matrix(db, "t1")}
    assert any(r["coverage"] == "passed" for r in rows.values()) and any(r["result"] == "Not run" for r in rows.values())


def test_a_stopped_run_marks_its_cases_cancelled(db, paths, tmp_path):
    put_story(db)
    analysed(db, paths, accept=1)
    bridge.generate(db, "t1", "QPL-2")
    ex = bridge.plan(db, "t1", ["TC-QPL-2-1"], "requirements", {"url": "https://x"})["execution"]
    done = bridge.collect(db, "t1", ex["id"], tmp_path / "missing", "stopped")
    assert done["status"] == "stopped" and done["counts"] == {"Cancelled": 1}


def test_tenants_never_see_each_others_test_cases(db, paths):
    put_story(db, tenant="t1")
    put_story(db, tenant="t2")
    analysed(db, paths, tenant="t1")
    bridge.generate(db, "t1", "QPL-2")
    assert bridge.list_cases(db, "t2") == [] and bridge.get_case(db, "t2", "TC-QPL-2-1") is None
    with pytest.raises(LookupError):
        bridge.plan(db, "t2", ["TC-QPL-2-1"], "requirements", {"url": "https://x"})


# ================================================================ the API

@pytest.fixture
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.tenancy_store as tenancy
    from backend import server
    mock = MockJira()
    mock.projects = [{"id": "7", "key": "QPL", "name": "Qpilot1"}]
    mock.issues["QPL-2"] = story("QPL-2", "User Login Functionality", T0, "", "")
    mock.issues["QPL-2"]["fields"]["description"] = adf(
        "AC1: A valid username and password open the products page",
        "AC2: A wrong password shows 'Username and password do not match'")
    monkeypatch.setattr(approvals, "DEFAULT_DB", tmp_path / "approvals.sqlite")
    monkeypatch.setattr(store, "DEFAULT_DB", tmp_path / "req.sqlite")
    monkeypatch.setattr(audit_store, "DEFAULT_DB", tmp_path / "audit.sqlite")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", tmp_path / "tenancy.sqlite")
    monkeypatch.setattr(credentials, "DEFAULT_FILE", tmp_path / "creds.json")
    monkeypatch.setattr(rapi, "CLIENT_BASE_URL", mock.url)
    monkeypatch.setattr(rapi, "JOBS", rapi.Jobs())
    for key in ("QPILOT_DASHBOARD_AUTH", "JIRA_READ_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    H = {"X-Agentic-QA": "1"}
    client.post("/api/requirements/connections", headers=H, json={"id": "jira-main", "product": "jira",
                                                                   "site_url": SITE, "email": EMAIL})
    client.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    job = client.post("/api/requirements/connections/jira-main/imports", headers=H,
                      json={"mode": "items", "keys": "QPL-2"}).json()
    rapi.JOBS.wait(job["id"])
    a = client.post("/api/requirements/items/jira-main/QPL-2/analyze", headers=H, json={}).json()["analysis"]
    yield SimpleNamespace(client=client, H=H, analysis=a, server=server, mock=mock, tmp=tmp_path)
    mock.close()


def _accept(api, n):
    for s in api.analysis["suggestions"][:n]:
        api.client.post(f"/api/requirements/items/jira-main/QPL-2/suggestions/{quote(s['id'], safe='')}/review",
                        headers=api.H, json={"answer": "yes"})


def test_generate_list_and_inspect_test_cases_through_the_api(api):
    r = api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    assert r.status_code == 200 and r.json()["created"] == []  # (nothing accepted yet: nothing generated)
    _accept(api, 2)
    r = api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H).json()
    assert r["created"] == ["TC-QPL-2-1", "TC-QPL-2-2"] and len(r["test_cases"]) == 2
    one = api.client.get("/api/requirements/test-cases/TC-QPL-2-1").json()
    assert one["test_case"]["reviewer"] == "local-user" and one["history"][0]["event"].startswith("generated")
    assert api.client.get("/api/requirements/test-cases?requirement=QPL-2").json()["total"] == 2
    caps = api.client.get("/api/requirements/capabilities").json()["capabilities"]
    assert caps["generate_test_cases"] and caps["run_selected_tests"] and not caps["jira_write_back"]


def test_an_execution_hands_only_ready_cases_to_the_existing_run(api, monkeypatch):
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    api.client.put("/api/requirements/test-cases/TC-QPL-2-2", headers=api.H, json={"title": "Changed title"})
    launched = {}

    def fake_launch(req, caller):  # (the real launcher starts main.py: covered by the end-to-end run test)
        launched["req"] = req
        api.server.jobs[4242] = {"id": 4242, "status": "running", "run": ""}
        return {"id": 4242}
    monkeypatch.setattr(api.server, "_launch_run", fake_launch)
    body = {"strategy": "requirements", "scope": {"requirements": ["QPL-2"]},
            "target": {"url": "https://www.saucedemo.com/", "authorized": True, "test_username": "standard_user",
                       "test_password": "secret_sauce"}}
    refused = api.client.post("/api/requirements/executions", headers=api.H,
                              json={**body, "target": {**body["target"], "authorized": False}})
    assert refused.status_code == 400 and "permission" in refused.json()["detail"]
    r = api.client.post("/api/requirements/executions", headers=api.H, json=body)
    assert r.status_code == 200, r.text
    ex = r.json()["execution"]
    assert ex["case_ids"] == ["TC-QPL-2-1"]  # (TC-QPL-2-2 was edited: it waits for approval)
    req = launched["req"]
    assert req.requirements_only and req.objective_focus and req.test_username == "standard_user"
    assert [t["tc"] for t in req.requirement_tests] == ["TC-QPL-2-1"]
    assert "secret_sauce" not in r.text and "secret_sauce" not in json.dumps(ex)
    run = api.tmp / "runs" / "run1"
    run.mkdir(parents=True)
    (run / "test_cases.json").write_text(json.dumps([{"requirement_test": "TC-QPL-2-1", "execution_status": "Failed",
                                                      "actual_result": "stayed on the login page",
                                                      "evidence": ["failure_screenshots/a.png"]}]))
    api.server.jobs[4242].update(status="done", run="run1")
    monkeypatch.setattr(api.server, "_plain_run_dir", lambda name: run)
    got = api.client.get(f"/api/requirements/executions/{ex['id']}").json()
    assert got["execution"]["status"] == "finished" and got["results"][0]["status"] == "Failed"
    assert got["results"][0]["actual"] == "stayed on the login page"
    tr = api.client.get("/api/requirements/traceability").json()["rows"]
    assert any(row["test_case"] == "TC-QPL-2-1" and row["result"] == "Failed" for row in tr)
    cov = api.client.get("/api/requirements/coverage/execution").json()["coverage"]
    assert cov["executed"] == 1 and cov["passed"] == 0 and cov["failed"] == 1
    failed_again = api.client.post("/api/requirements/executions", headers=api.H,
                                   json={**body, "scope": {"failed": True}}).json()["execution"]
    assert failed_again["case_ids"] == ["TC-QPL-2-1"]
    api.server.jobs.pop(4242, None)


def test_test_case_approval_needs_a_named_person(api, monkeypatch):
    _accept(api, 1)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    api.client.put("/api/requirements/test-cases/TC-QPL-2-1", headers=api.H, json={"expected": "Products page"})
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "bearer")
    monkeypatch.setenv("QPILOT_DASHBOARD_TOKEN", "shared-token-12345")
    r = api.client.post("/api/requirements/test-cases/TC-QPL-2-1/approve",
                        headers={**api.H, "Authorization": "Bearer shared-token-12345"})
    assert r.status_code == 403
    monkeypatch.delenv("QPILOT_DASHBOARD_AUTH")
    monkeypatch.delenv("QPILOT_DASHBOARD_TOKEN")
    r = api.client.post("/api/requirements/test-cases/TC-QPL-2-1/approve", headers=api.H)
    assert r.status_code == 200 and r.json()["test_case"]["status"] == "approved"


def test_nothing_runs_without_an_approved_test_case(api):
    r = api.client.post("/api/requirements/executions", headers=api.H, json={
        "strategy": "requirements", "scope": {"all_approved": True},
        "target": {"url": "https://www.saucedemo.com/", "authorized": True}})
    assert r.status_code == 400 and "Generate test cases" in r.json()["detail"]


def test_a_skipped_not_automated_case_is_never_counted_as_executed(db, paths, tmp_path):
    """Seen in a real run: the engine reported 'Skipped' with 'Not automated: the AI could not write working code'."""
    put_story(db)
    analysed(db, paths, accept=1)
    bridge.generate(db, "t1", "QPL-2")
    ex = bridge.plan(db, "t1", ["TC-QPL-2-1"], "requirements", {"url": "https://x"})["execution"]
    run = tmp_path / "run2"
    run.mkdir()
    (run / "test_cases.json").write_text(json.dumps([{
        "requirement_test": "TC-QPL-2-1", "execution_status": "Skipped",
        "skip_reason": "Not automated: the AI could not write working code for it this time"}]))
    done = bridge.collect(db, "t1", ex["id"], run)
    assert done["counts"] == {"Not automated": 1}
    assert bridge.coverage(db, "t1")["executed"] == 0
    assert [r["coverage"] for r in bridge.matrix(db, "t1") if r["test_case"]] == ["not automated"]


def test_a_message_quoted_by_an_approved_requirement_test_is_grounded_but_invented_selectors_are_not(monkeypatch):
    """Live SauceDemo run: the wrong-password message appears only after the steps, so exploring never saw it. The
    requirement's own quoted words are evidence; a CSS selector the explorer never saw still is not."""
    from backend.agents import script_generator
    from backend.ai_grounding import grounding_problem
    pages = [{"slug": "login", "url": "https://shop.test/", "inputs": [{"selector": "#user-name"}],
              "buttons": [{"selector": "#login-button", "text": "Login"}]}]
    quoted = "Username and password do not match any user in this service"
    by_text = f'def test_x(page):\n    expect(page.locator("body")).to_contain_text("{quoted}")\n'
    invented = 'def test_x(page):\n    expect(page.locator("h3[data-test=\'error\']")).to_be_visible()\n'
    monkeypatch.delenv(requirement_tests.ENV, raising=False)
    assert quoted.casefold() not in script_generator._requirement_evidence().casefold()
    monkeypatch.setenv(requirement_tests.ENV, json.dumps([{
        "id": "rq_tc_qpl_2_2", "tc": "TC-QPL-2-2", "requirement": "QPL-2",
        "text": f"Log in with a wrong password. Expected: the page shows '{quoted}'."}]))
    evidence = script_generator._requirement_evidence()
    assert quoted in evidence
    assert grounding_problem(by_text, pages, evidence) is None
    assert "was not observed" in (grounding_problem(invented, pages, evidence) or "")


def test_calling_the_login_fixture_like_a_function_is_caught_before_the_test_runs():
    """Live SauceDemo run: the AI wrote `user, password = qa_login()` without asking for the fixture -> NameError at
    run time. The static check now refuses it, so the AI's self-repair fixes it before anything runs."""
    from backend.agents.script_generator import validate_script
    called = "def test_a(page):\n    user, password = qa_login()\n    assert user\n"
    missing = "def test_a(page):\n    user, password = qa_login\n    assert user\n"
    right = "def test_a(page, qa_login):\n    user, password = qa_login\n    assert user\n"
    assert "fixture" in (validate_script(called) or "")
    assert "add qa_login to its parameters" in (validate_script(missing) or "")
    assert validate_script(right) is None


def test_a_test_that_would_type_a_removed_secret_is_refused():
    """Live SauceDemo run: the AI wrote the account name, secret masking turned it into '[REDACTED]', and the wrong-
    password test typed that as the user name (it passed, but did not test the valid user). Now refused, so the
    self-repair takes the account from qa_login."""
    from backend.agents.script_generator import validate_script
    code = ('def test_a(page):\n    page.locator("#user-name").fill("[REDACTED]")\n'
            '    page.locator("#password").fill("wrong")\n')
    assert "qa_login" in (validate_script(code) or "")


def test_an_instruction_that_needs_the_test_account_says_where_it_comes_from():
    case = {"title": "Wrong password", "preconditions": [], "steps": ["Log in with a wrong password"],
            "expected": "An error is shown", "assertions": [], "test_data_needs": ["a test account (user name and "
                                                                                  "password)"]}
    text = bridge.instruction(case)
    assert "qa_login" in text and "another password" in text
    assert "qa_login" not in bridge.instruction({**case, "test_data_needs": []})
