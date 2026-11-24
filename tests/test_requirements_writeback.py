# ruff: noqa: F811  (the shared `api` fixture is imported, then requested by name)
"""Requirements Intelligence, Phase 5: defect intelligence from REAL requirement results, and controlled Jira
write-back - off by default, separate write token, a named person's approval, preview, idempotency, audit.
Every write goes only to the local mock Jira; nothing here can reach a real Atlassian site."""
import json

import pytest

from backend import approvals
from backend.atlassian import bridge, defects, writeback
from backend.atlassian.client import AtlassianError, Client, WriteClient
from backend.atlassian.models import Connection
from tests.atlassian_mock import EMAIL, TOKEN
from tests.test_requirements_execution import _accept, api  # noqa: F401 (the shared fixture)

FAIL = {"execution_status": "Failed", "actual_result": "stayed on the login page after 3 seconds",
        "failure_category": "Application defect (potential website bug)", "confidence": "high",
        "evidence": ["failure_screenshots/login.png"]}


@pytest.fixture
def ready(api, monkeypatch):  # noqa: F811
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    state = {"n": 0}

    def fake_launch(req, caller):
        state["n"] += 1
        job = 7000 + state["n"]
        api.server.jobs[job] = {"id": job, "status": "running", "run": ""}
        return {"id": job}
    monkeypatch.setattr(api.server, "_launch_run", fake_launch)
    monkeypatch.delenv(writeback.SERVER_ENV, raising=False)

    def run(results: dict) -> str:
        """One execution of TC-QPL-2-1 / -2 whose run reports `results` (test case id -> engine fields)."""
        body = {"strategy": "requirements", "scope": {"requirements": ["QPL-2"]},
                "target": {"url": "https://www.saucedemo.com/", "authorized": True}}
        ex = api.client.post("/api/requirements/executions", headers=api.H, json=body).json()["execution"]
        folder = api.tmp / "runs" / ex["id"]
        folder.mkdir(parents=True)
        (folder / "test_cases.json").write_text(json.dumps([{"requirement_test": k, **v} for k, v in results.items()]))
        job = int(ex["run_id"])
        monkeypatch.setattr(api.server, "_plain_run_dir", lambda name, f=folder: f)
        api.server.jobs[job].update(status="done", run=ex["id"])
        got = api.client.get(f"/api/requirements/executions/{ex['id']}").json()
        assert got["execution"]["status"] == "finished"
        return ex["id"]
    yield run
    for k in [k for k in api.server.jobs if isinstance(k, int) and 7000 < k < 7100]:
        api.server.jobs.pop(k, None)


def _defects(api, **q):
    return api.client.get("/api/requirements/defects", params=q).json()


def _writes_to_jira(mock):
    return [r for r in mock.requests if r["method"] == "POST" and (
        r["path"] == "/rest/api/3/issue" or r["path"].endswith("/comment"))]


# ================================================================ defect intelligence

def test_a_failure_becomes_one_defect_that_resolves_and_reopens(api, ready):
    passed = {"execution_status": "Passed", "check_count": 3, "actual_result": "All checks passed"}
    ready({"TC-QPL-2-1": FAIL, "TC-QPL-2-2": {"execution_status": "Skipped", "skip_reason": "Not automated: no AI"}})
    d = _defects(api)
    assert d["total"] == 1  # (Not automated is never a defect)
    one = d["defects"][0]
    assert one["test_case_id"] == "TC-QPL-2-1" and one["requirement_id"] == "QPL-2" and one["status"] == "open"
    assert one["triage"] == "likely_defect" and one["severity"] == "high" and one["occurrences"] == 1
    assert one["evidence"] == ["failure_screenshots/login.png"] and one["regression"] is False
    ready({"TC-QPL-2-1": {**FAIL, "actual_result": "stayed on the login page after 7 seconds"}})
    again = _defects(api)["defects"]
    assert len(again) == 1 and again[0]["id"] == one["id"] and again[0]["occurrences"] == 2  # (same, not new)
    ready({"TC-QPL-2-1": passed})
    assert _defects(api)["defects"][0]["status"] == "resolved"
    ready({"TC-QPL-2-1": FAIL})
    back = _defects(api)["defects"][0]
    assert back["status"] == "reopened" and back["regression"] is True and back["occurrences"] == 3
    rows = api.client.get("/api/requirements/traceability").json()["rows"]
    assert any(r["test_case"] == "TC-QPL-2-1" and r["defects"][0]["id"] == one["id"] for r in rows)


def test_test_problems_are_not_application_bugs_and_dismissal_needs_a_reason(api, ready):
    ready({"TC-QPL-2-1": {**FAIL, "failure_category": "Locator / interaction failure (not proof of a website bug)"},
           "TC-QPL-2-2": {**FAIL, "actual_result": "no error message", "failure_category": ""}})
    by = {d["test_case_id"]: d for d in _defects(api)["defects"]}
    assert by["TC-QPL-2-1"]["triage"] == "test_problem" and by["TC-QPL-2-1"]["severity"] == "low"
    assert by["TC-QPL-2-2"]["triage"] == "needs_triage"
    r = api.client.post("/api/requirements/writeback/proposals", headers=api.H,
                        json={"defect_id": by["TC-QPL-2-1"]["id"]})
    assert r.status_code == 409 and "not proposed as an application bug" in r.json()["detail"]
    did = by["TC-QPL-2-2"]["id"]
    assert api.client.post(f"/api/requirements/defects/{did}/dismiss", headers=api.H,
                           json={"reason": ""}).status_code == 422
    ok = api.client.post(f"/api/requirements/defects/{did}/dismiss", headers=api.H,
                         json={"reason": "the requirement allows no message"}).json()["defect"]
    assert ok["status"] == "dismissed" and ok["dismissed_by"] == "local-user"
    assert _defects(api, status="dismissed")["defects"][0]["dismissed_reason"] == "the requirement allows no message"


# ================================================================ write-back: proposals, approval, refusals

def test_proposals_are_previewed_and_idempotent_and_nothing_is_sent(api, ready):
    ex = ready({"TC-QPL-2-1": FAIL, "TC-QPL-2-2": {"execution_status": "Passed", "check_count": 2}})
    r = api.client.post("/api/requirements/writeback/proposals", headers=api.H, json={"execution_id": ex}).json()
    w = r["writes"][0]
    assert w["operation"] == "add_comment" and w["target"] == "QPL-2" and w["status"] == "proposed"
    text = w["payload"]["text"]
    assert "TC-QPL-2-1" in text and "Failed" in text and "TC-QPL-2-2" in text and "1 of 2 test cases passed" in text
    assert writeback.marker(w["idempotency_key"]) in json.dumps(w["preview"])  # (the exact JSON that would be sent)
    again = api.client.post("/api/requirements/writeback/proposals", headers=api.H, json={"execution_id": ex}).json()
    assert again["writes"][0]["id"] == w["id"]  # (the same write is one proposal)
    did = _defects(api)["defects"][0]["id"]
    bug = api.client.post("/api/requirements/writeback/proposals", headers=api.H, json={"defect_id": did}).json()
    b = bug["writes"][0]
    assert b["operation"] == "create_issue" and b["target"] == "QPL" and b["payload"]["links_to"] == "QPL-2"
    assert "Expected:" in b["payload"]["description"] and "stayed on the login page" in b["payload"]["description"]
    assert b["preview"]["update"]["issuelinks"][0]["add"]["outwardIssue"]["key"] == "QPL-2"
    state = api.client.get("/api/requirements/writeback").json()
    assert len(state["writes"]) == 2 and state["server_allows"] is False
    assert state["connections"][0]["can_send"] is False
    assert _writes_to_jira(api.mock) == []


def test_write_back_is_off_until_the_owner_the_workspace_and_a_reviewer_all_allow_it(api, ready, monkeypatch):
    ex = ready({"TC-QPL-2-1": FAIL})
    w = api.client.post("/api/requirements/writeback/proposals", headers=api.H,
                        json={"execution_id": ex}).json()["writes"][0]
    caps = api.client.get("/api/requirements/capabilities").json()
    assert caps["capabilities"]["jira_write_back"] is False and caps["read_only_atlassian"] is True
    r = api.client.put("/api/requirements/writeback/settings/jira-main", headers=api.H,
                       json={"enabled": True, "project_key": "QPL"})
    assert r.status_code == 403 and writeback.SERVER_ENV in r.json()["detail"]
    r = api.client.post(f"/api/requirements/writeback/{w['id']}/send", headers=api.H)
    assert r.status_code == 403 and "only an approved write" in r.json()["detail"]
    approved = api.client.post(f"/api/requirements/writeback/{w['id']}/approve", headers=api.H).json()["write"]
    assert approved["status"] == "approved" and approved["approved_by"] == "local-user" and approved["approval_id"]
    assert approvals.get_approval(approved["approval_id"])["decided_by"] == "local-user"
    r = api.client.post(f"/api/requirements/writeback/{w['id']}/send", headers=api.H)
    assert r.status_code == 403 and "server owner" in r.json()["detail"]  # (approved, still not sent: off)
    monkeypatch.setenv(writeback.SERVER_ENV, "1")
    assert api.client.put("/api/requirements/writeback/settings/jira-main", headers=api.H,
                          json={"enabled": True, "project_key": "QPL"}).status_code == 200
    r = api.client.post(f"/api/requirements/writeback/{w['id']}/send", headers=api.H)
    assert r.status_code == 403 and "write token" in r.json()["detail"]  # (the READ token never writes)
    assert _writes_to_jira(api.mock) == []
    # the generic approvals route cannot decide a Jira write
    row = approvals.create("jira_write", "x", tenant_id="local")
    assert api.client.post(f"/api/approvals/{row['id']}/decide", headers=api.H,
                           json={"answer": "yes"}).status_code == 409


def test_an_approved_write_is_sent_once_with_the_write_token(api, ready, monkeypatch):
    monkeypatch.setenv(writeback.SERVER_ENV, "1")
    ex = ready({"TC-QPL-2-1": FAIL})
    api.client.put("/api/requirements/writeback/settings/jira-main", headers=api.H,
                   json={"enabled": True, "project_key": "QPL"})
    saved = api.client.put("/api/requirements/writeback/token", headers=api.H, json={"token": TOKEN})
    assert saved.status_code == 200 and TOKEN not in saved.text
    w = api.client.post("/api/requirements/writeback/proposals", headers=api.H,
                        json={"execution_id": ex}).json()["writes"][0]
    api.client.post(f"/api/requirements/writeback/{w['id']}/approve", headers=api.H)
    sent = api.client.post(f"/api/requirements/writeback/{w['id']}/send", headers=api.H).json()["write"]
    assert sent["status"] == "sent" and sent["remote_id"] and sent["sent_by"] == "local-user"
    comments = api.mock.comments["QPL-2"]
    assert len(comments) == 1 and writeback.marker(w["idempotency_key"]) in json.dumps(comments[0]["body"])
    again = api.client.post(f"/api/requirements/writeback/{w['id']}/send", headers=api.H).json()["write"]
    assert again["status"] == "sent" and len(api.mock.comments["QPL-2"]) == 1  # (never twice)
    # a defect: one Bug, labelled with its marker, linked to the story; the defect records the new key
    did = _defects(api)["defects"][0]["id"]
    b = api.client.post("/api/requirements/writeback/proposals", headers=api.H,
                        json={"defect_id": did}).json()["writes"][0]
    api.client.post(f"/api/requirements/writeback/{b['id']}/approve", headers=api.H)
    bug = api.client.post(f"/api/requirements/writeback/{b['id']}/send", headers=api.H).json()["write"]
    assert bug["status"] == "sent" and len(api.mock.created) == 1
    created = api.mock.created[0]["body"]
    assert writeback.marker(b["idempotency_key"]) in created["fields"]["labels"]
    assert created["fields"]["issuetype"]["name"] == "Bug" and created["fields"]["project"]["key"] == "QPL"
    assert _defects(api)["defects"][0]["jira_issue"] == bug["remote_id"]
    r = api.client.post("/api/requirements/writeback/proposals", headers=api.H, json={"defect_id": did})
    assert r.status_code == 409 and "already reported" in r.json()["detail"]
    from backend import audit_store
    events = [json.loads(e["detail"])["event"] for e in audit_store.list_audits(limit=200)
              if e["action"] == writeback.ACTION]
    assert {"proposed", "approved", "sent"} <= set(events)
    assert TOKEN not in json.dumps(api.client.get("/api/requirements/writeback").json())


def test_a_write_whose_answer_was_lost_is_found_in_jira_not_repeated(api, ready, monkeypatch):
    monkeypatch.setenv(writeback.SERVER_ENV, "1")
    ex = ready({"TC-QPL-2-1": FAIL})
    api.client.put("/api/requirements/writeback/settings/jira-main", headers=api.H, json={"enabled": True})
    api.client.put("/api/requirements/writeback/token", headers=api.H, json={"token": TOKEN})
    w = api.client.post("/api/requirements/writeback/proposals", headers=api.H,
                        json={"execution_id": ex}).json()["writes"][0]
    api.client.post(f"/api/requirements/writeback/{w['id']}/approve", headers=api.H)
    api.mock.drop_write_answer = 1  # (Jira applies the comment, the answer never arrives)
    first = api.client.post(f"/api/requirements/writeback/{w['id']}/send", headers=api.H).json()["write"]
    assert first["status"] == "failed" and first["last_error"].startswith("network")
    assert len(api.mock.comments["QPL-2"]) == 1
    retry = api.client.post(f"/api/requirements/writeback/{w['id']}/send", headers=api.H).json()["write"]
    assert retry["status"] == "sent" and retry["remote_id"] == api.mock.comments["QPL-2"][0]["id"]
    assert len(api.mock.comments["QPL-2"]) == 1 and len(_writes_to_jira(api.mock)) == 1
    assert "not sent again" in retry["history"][-1]["event"]


def test_only_the_write_client_writes_and_only_two_kinds_of_write(api):
    conn = Connection(id="jira-main", tenant_id="local", product="jira", site_url="https://acme-test.atlassian.net",
                      email=EMAIL, token_ref="JIRA_WRITE_API_TOKEN")
    reader = Client(conn, secret=lambda n: TOKEN, base_url=api.mock.url)
    with pytest.raises(AtlassianError) as e:
        reader._request("POST", "/rest/api/3/issue/QPL-2/comment", payload={}, write=True)
    assert e.value.kind == "refused"
    w = WriteClient(conn, secret=lambda n: TOKEN, base_url=api.mock.url)
    for path in ("/rest/api/3/issue/QPL-2", "/rest/api/3/issue/QPL-2/transitions", "/rest/api/3/project"):
        with pytest.raises(AtlassianError):
            w.post_write(path, {})
    for method in ("PUT", "DELETE"):
        with pytest.raises(AtlassianError):
            w._request(method, "/rest/api/3/issue/QPL-2/comment", payload={}, write=True)
    assert _writes_to_jira(api.mock) == []


def test_defect_records_are_per_tenant(api, ready):
    ready({"TC-QPL-2-1": FAIL})
    db = bridge.connect()
    try:
        defects.refresh(db, "other-tenant")
        assert defects.list_defects(db, "other-tenant") == []
        assert len(defects.list_defects(db, "local")) == 1
    finally:
        db.close()
