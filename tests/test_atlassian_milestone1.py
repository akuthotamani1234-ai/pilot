"""Requirements Intelligence, Milestone 1: the audit findings fixed.

Criteria extraction (headingless AC labels, heading variants, notes never criteria), configurable work-item types and
their discovery, the zero-result warning, read credentials separate from the defect-creation token, no write path,
approval queue and analysis kept in step, named reviewers from the login, tenant isolation, redaction of custom secret
names, and the read-only command line. Everything runs against tests/atlassian_mock.py on 127.0.0.1."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import approvals, audit_store, privacy, safety
from backend.atlassian import analysis as an, cli, jira, store
from backend.atlassian.client import AtlassianError, Client
from backend.atlassian.models import Connection
from backend.atlassian.sync import sync_jira
from tests.atlassian_mock import EMAIL, T0, TOKEN, MockJira, adf, story

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://acme-test.atlassian.net"


@pytest.fixture
def mock():
    m = MockJira()
    yield m
    m.close()


@pytest.fixture
def db(tmp_path):
    d = store.connect(tmp_path / "req.sqlite")
    yield d
    d.close()


def conn(tenant="t1", **kw):
    return Connection(**{"id": "jira-main", "tenant_id": tenant, "product": "jira", "site_url": SITE,
                         "email": EMAIL, "token_ref": "JIRA_READ_API_TOKEN", **kw})


def client(mock, connection=None):
    return Client(connection or conn(), base_url=mock.url, secret=lambda n: TOKEN, sleep=lambda s: None)


def criteria_of(description: str, ac_text: str = "") -> list[str]:
    """The criteria texts the analysis reads from one Jira description (and AC field)."""
    issue = story("QPL-2", "User Login Functionality", T0, "", "")
    issue["fields"]["description"] = adf(*description.split("\n")) if description else None
    issue["fields"]["customfield_10045"] = adf(*ac_text.split("\n")) if ac_text else None
    item = jira.normalize(issue, conn(), ac_field="customfield_10045" if ac_text else "", retrieved_at=T0)
    return [words for words, _ in an._from_story(item["source"], item["story"])]


# ---------------------------------------------------------------- 1 extraction

@pytest.mark.parametrize("description, expected", [
    ("AC1: The user enters a shipping address\nAC2: The order total includes tax",
     ["The user enters a shipping address", "The order total includes tax"]),
    ("Intro text.\nAC-1: Cart shows each product\nAC 2 - Quantity can be changed\n"
     "Acceptance criterion 3: Removing an item updates the total",
     ["Cart shows each product", "Quantity can be changed", "Removing an item updates the total"]),
    ("- AC1: Sorting by price works\n- AC2: Sorting by name works", ["Sorting by price works", "Sorting by name works"]),
    ("AC1: Given a logged-in user\nWhen they open the cart\nThen the cart is shown\nUnrelated sentence.",
     ["Given a logged-in user When they open the cart Then the cart is shown"]),
])
def test_headingless_labelled_criteria_are_read(description, expected):
    assert criteria_of(description) == expected


@pytest.mark.parametrize("heading", ["Acceptance Criteria", "Acceptance Criteria:", "AcceptanceCriteria:",
                                     "Acceptance_Criteria", "## Acceptance criteria", "Acceptance Criteria (AC)",
                                     "Acceptance Criteria ✅", "ACs:", "AC", "Definition of Done",
                                     "Conditions of satisfaction:", "Acceptance criterion"])
def test_heading_variations_open_the_criteria(heading):
    assert criteria_of(f"As a shopper I want to log in.\n{heading}\n- Valid login opens the dashboard\n"
                       "- A wrong password shows an error") == ["Valid login opens the dashboard",
                                                                "A wrong password shows an error"]


def test_an_inline_acceptance_criteria_label_is_a_criterion():
    assert criteria_of("Acceptance Criteria: The order summary lists every item") == [
        "The order summary lists every item"]


@pytest.mark.parametrize("other", ["Notes: design is in Figma", "References: QPL-1", "Out of scope",
                                   "## Notes", "Technical notes: use the v2 API", "Dependencies: payment service",
                                   "Open questions:", "Links: https://example.test", "Attachments (2):"])
def test_notes_references_and_other_text_never_become_criteria(other):
    got = criteria_of(f"Acceptance Criteria\n- Order id is shown\n{other}\n- not a criterion either")
    assert got == ["Order id is shown"]


def test_notes_in_the_acceptance_criteria_field_are_cut_too():
    assert criteria_of("", "1. Totals include tax\nNotes:\n2. reviewed by Sam") == ["Totals include tax"]


def test_a_second_criteria_heading_reopens_after_notes():
    assert criteria_of("Acceptance criteria\n- First rule holds\nNotes: x\nBusiness rules\n- Second rule holds") == [
        "First rule holds", "Second rule holds"]


def test_a_plain_numbered_list_without_heading_is_not_taken_as_criteria():
    # (steps to reproduce look the same; nothing is invented - the analysis reports missing criteria instead)
    assert criteria_of("Steps:\n1. Open the site\n2. Click login") == []


@pytest.mark.parametrize("text", ["The ACME 1. release", "Uses AC 220V power", "Accent 3: colours"])
def test_words_that_look_like_ac_labels_are_not_criteria(text):
    assert criteria_of(text) == []


@pytest.mark.parametrize("name, wins", [("Acceptance Criteria", True), ("AcceptanceCriteria", True),
                                        ("Acceptance_Criteria", True), ("Acceptance criterion", True),
                                        ("ACs", True), ("Definition of Done", True), ("Account", False),
                                        ("Accessibility notes", False)])
def test_the_acceptance_criteria_field_is_found_by_its_name_variants(mock, name, wins):
    mock.fields = [{"id": "customfield_20001", "name": name, "custom": True}]
    assert jira.acceptance_field(client(mock)) == ("customfield_20001" if wins else "")


def test_the_exact_acceptance_criteria_field_wins_over_a_variant(mock):
    mock.fields = [{"id": "customfield_1", "name": "Definition of Done", "custom": True},
                   {"id": "customfield_9", "name": "Acceptance Criteria", "custom": True}]
    assert jira.acceptance_field(client(mock)) == "customfield_9"


# ---------------------------------------------------------------- 2 work-item types and the zero-result warning

def _add(mock, key, type_name, description="Acceptance Criteria\n- Login works"):
    mock.issues[key] = story(key, f"{type_name} {key}", T0, description, "", issuetype={"name": type_name})


def test_work_item_types_are_discovered_with_counts(mock):
    _add(mock, "SHOP-1", "Task")
    _add(mock, "SHOP-2", "Task")
    _add(mock, "SHOP-3", "Story")
    c = client(mock)
    types = jira.work_item_types(c, "SHOP")
    assert [t["name"] for t in types] == ["Epic", "Story", "Task", "Bug", "Subtask"]
    assert {t["name"]: t["count"] for t in jira.type_counts(c, "SHOP", types)} == {
        "Epic": 0, "Story": 1, "Task": 2, "Bug": 0}  # (sub-tasks are not requirements)


def test_a_sync_of_the_wrong_type_warns_and_names_the_real_types(mock, db):
    _add(mock, "SHOP-1", "Task")
    _add(mock, "SHOP-2", "Task")
    result = sync_jira(db, conn(), client(mock), tenant_id="t1", project="SHOP", audit_db=db_path(db))
    assert result["status"] == "complete" and result["new"] == 0
    assert result["work_item_types"] == ["Story"]
    assert len(result["warnings"]) == 1
    assert "0 work items imported from SHOP (types: Story)" in result["warnings"][0]
    assert "SHOP has: Task (2)" in result["warnings"][0]


def test_configured_task_and_custom_types_are_imported(mock, db):
    _add(mock, "SHOP-1", "Task")
    _add(mock, "SHOP-2", "User Story")
    _add(mock, "SHOP-3", "Bug")
    c = conn(work_item_types=["Task", "User Story"])
    result = sync_jira(db, c, client(mock, c), tenant_id="t1", project="SHOP", audit_db=db_path(db))
    assert result["new"] == 2 and result["warnings"] == []
    assert 'issuetype in ("Task", "User Story")' in result["scope"]
    # an explicit override wins over the connection's types
    again = sync_jira(db, c, client(mock, c), tenant_id="t1", project="SHOP", issue_types=["Bug"],
                      audit_db=db_path(db))
    assert again["new"] == 1 and again["work_item_types"] == ["Bug"]


def test_an_unknown_project_or_an_empty_one_gets_a_clear_warning(mock, db):
    result = sync_jira(db, conn(), client(mock), tenant_id="t1", project="SHOP", audit_db=db_path(db))
    assert "SHOP has no work items this account can see" in result["warnings"][0]


def test_incremental_syncs_with_no_change_do_not_warn(mock, db):
    _add(mock, "SHOP-1", "Story")
    sync_jira(db, conn(), client(mock), tenant_id="t1", project="SHOP", audit_db=db_path(db))
    again = sync_jira(db, conn(), client(mock), tenant_id="t1", project="SHOP", audit_db=db_path(db))
    assert again["status"] == "complete" and again["warnings"] == []


def test_work_item_type_names_are_validated():
    assert conn(work_item_types=[" Task ", "task", "User  Story"]).work_item_types == ["Task", "User Story"]
    for bad in ([], ["Story\nAND project = X"], ["x" * 61], ["T"] * 21):
        with pytest.raises(ValueError):
            conn(work_item_types=bad)


def test_the_story_type_maps_to_the_requirement_kind(mock, db):
    _add(mock, "SHOP-1", "Task")
    c = conn(work_item_types=["Task"])
    store.save_connection(db, c)
    sync_jira(db, c, client(mock, c), tenant_id="t1", project="SHOP", audit_db=db_path(db))
    req = an.build_requirement(db, "t1", "jira-main:jira_issue:SHOP-1")
    assert req.kind == "task" and [x.text for x in req.criteria] == ["Login works"]


def db_path(db) -> Path:
    return Path(db.execute("PRAGMA database_list").fetchone()[2]).with_name("audit.sqlite")


# ---------------------------------------------------------------- 3 credentials and writes

@pytest.mark.parametrize("name", ["JIRA_API_TOKEN", "OPENAI_API_KEY", "TEST_PASSWORD", "GITHUB_TOKEN",
                                  "MY_TOKEN", "JIRA_URL"])
def test_the_read_connection_never_uses_the_defect_token_or_another_secret(name):
    with pytest.raises(ValueError):
        conn(token_ref=name)


@pytest.mark.parametrize("name", ["JIRA_READ_API_TOKEN", "CONFLUENCE_API_TOKEN", "ATLASSIAN_QPL_TOKEN",
                                  "JIRA_TEAM_B_SECRET", "QPILOT_SECRET_JIRA_READ"])
def test_custom_read_secret_names_are_allowed(name):
    assert conn(token_ref=name).token_ref == name


@pytest.mark.parametrize("method, path", [("POST", "/rest/api/3/issue"), ("PUT", "/rest/api/3/issue/SHOP-1"),
                                          ("DELETE", "/rest/api/3/issue/SHOP-1"),
                                          ("POST", "/rest/api/3/issue/SHOP-1/comment")])
def test_the_client_refuses_every_write_even_through_its_private_method(mock, method, path):
    c = client(mock)
    with pytest.raises(AtlassianError) as e:
        c._request(method, path, payload={"fields": {}})
    assert e.value.kind == "refused"
    assert mock.requests == []  # (nothing reached the site)


def test_no_module_of_the_package_sends_http_except_the_client():
    """Static check: requests / urllib / http.client appear only in client.py, and only GET / read POSTs are used."""
    for path in (ROOT / "backend" / "atlassian").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        if path.name != "client.py":
            assert not imported & {"requests", "urllib3", "http", "httpx", "aiohttp"}, path.name
        calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        assert not {"put", "delete", "patch"} & set(calls), path.name


def test_the_legacy_defect_creation_is_reported_when_it_would_write(monkeypatch):
    env = {"JIRA_URL": SITE, "JIRA_EMAIL": EMAIL, "JIRA_API_TOKEN": "x" * 20, "JIRA_PROJECT": "QPL"}
    assert cli.legacy_write_status(env) == {"active": True, "project": "QPL", "site": SITE}
    assert cli.legacy_write_status({**env, "JIRA_PROJECT": ""})["active"] is False
    assert cli.legacy_write_status({"JIRA_READ_API_TOKEN": "x" * 20})["active"] is False


# ---------------------------------------------------------------- 4 redaction of every credential name

def test_custom_secret_names_are_redacted_and_kept_from_workers(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_QPL_TOKEN", "custom-secret-value-8742")
    monkeypatch.setenv("QPILOT_SECRET_JIRA_READ", "prefixed-secret-value-1199")
    assert "custom-secret-value-8742" in safety.secret_values()
    assert safety.redact("token=custom-secret-value-8742") == "token=[REDACTED]"
    cleaned = safety.clean_env(dict(__import__("os").environ))
    assert "ATLASSIAN_QPL_TOKEN" not in cleaned and "QPILOT_SECRET_JIRA_READ" not in cleaned


def test_a_registered_token_ref_outside_the_pattern_is_redacted_too(monkeypatch):
    monkeypatch.setattr(safety, "_REGISTERED_SECRET_NAMES", set())
    monkeypatch.setenv("QPILOT_SECRET_X", "abc")  # (short values are not redacted: too likely to be words)
    monkeypatch.setenv("JIRA_ODD_NAME", "registered-value-5566")
    assert "registered-value-5566" not in safety.secret_values()
    safety.register_secret_names("JIRA_ODD_NAME")
    assert "registered-value-5566" in safety.secret_values()


def test_saving_or_using_a_connection_registers_its_secret_name(monkeypatch, db, mock):
    monkeypatch.setattr(safety, "_REGISTERED_SECRET_NAMES", set())
    store.save_connection(db, conn(token_ref="ATLASSIAN_TEAM_TOKEN"))
    assert "ATLASSIAN_TEAM_TOKEN" in safety.extra_secret_names({})
    monkeypatch.setattr(safety, "_REGISTERED_SECRET_NAMES", set())
    client(mock, conn(token_ref="CONFLUENCE_DOCS_KEY"))
    assert "CONFLUENCE_DOCS_KEY" in safety.extra_secret_names({})


@pytest.mark.parametrize("mode", ["local", "cloud"])
def test_read_tokens_never_reach_test_workers(monkeypatch, mode):
    monkeypatch.setattr(privacy, "load_policy", lambda: SimpleNamespace(mode=mode, cloud_consent=True))
    monkeypatch.setattr(privacy, "select_provider", lambda *a: "none")
    monkeypatch.setattr(privacy, "public_policy", lambda p: {})
    env = {"JIRA_READ_API_TOKEN": "a" * 20, "CONFLUENCE_API_TOKEN": "b" * 20, "ATLASSIAN_QPL_TOKEN": "c" * 20,
           "JIRA_API_TOKEN": "d" * 20}
    privacy.apply_worker_policy(env)
    assert env["JIRA_READ_API_TOKEN"] == env["CONFLUENCE_API_TOKEN"] == env["ATLASSIAN_QPL_TOKEN"] == ""
    # the older defect creation runs in the worker: its token stays in cloud mode only
    assert env["JIRA_API_TOKEN"] == ("" if mode == "local" else "d" * 20)


def test_a_saved_connection_with_the_old_token_name_asks_to_be_saved_again(db):
    data = json.loads(conn().model_dump_json()) | {"token_ref": "JIRA_API_TOKEN"}
    with db:
        db.execute("INSERT INTO connections (tenant_id, id, data, updated_at) VALUES ('t1', 'old', ?, 'now')",
                   (json.dumps(data),))
    with pytest.raises(ValueError, match="save it again"):
        store.get_connection(db, "t1", "old")


# ---------------------------------------------------------------- 5 approval queue <-> analysis, reviewers, tenants

@pytest.fixture
def api(monkeypatch, tmp_path):
    """The real Studio server with its stores in tmp_path; one analysed requirement with suggestions."""
    from fastapi.testclient import TestClient

    import backend.tenancy_store as tenancy
    from backend import server
    monkeypatch.setattr(approvals, "DEFAULT_DB", tmp_path / "approvals.sqlite")
    monkeypatch.setattr(store, "DEFAULT_DB", tmp_path / "req.sqlite")
    monkeypatch.setattr(audit_store, "DEFAULT_DB", tmp_path / "audit.sqlite")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", tmp_path / "tenancy.sqlite")
    db = store.connect()
    for tenant in ("t1", "t2"):
        c = conn(tenant)
        store.save_connection(db, c)
        issue = story("SHOP-12", "Login", T0, "Acceptance Criteria\n- A wrong password shows 'Invalid credentials'\n"
                                              "- Passwords must have at least 8 characters", "")
        item = jira.normalize(issue, c, retrieved_at=T0)
        store.upsert_source(db, item["source"], item["story"])
        an.analyze(db, tenant, "jira-main:jira_issue:SHOP-12", actor="system")
    tenancy.upsert_tenant("t1", "One")
    tenancy.upsert_tenant("t2", "Two")
    tenancy.upsert_principal("alice", "t1", "a@ex.test", "operator")
    tenancy.upsert_principal("bob", "t2", "b@ex.test", "admin")
    tenancy.upsert_principal("viewer-1", "t1", "v@ex.test", "viewer")
    yield SimpleNamespace(client=TestClient(server.app, base_url="http://127.0.0.1:8000"), db=db)
    db.close()


H = {"X-Agentic-QA": "1"}


def _suggestion(db, tenant="t1", n=0):
    return store.get_analysis(db, tenant, "SHOP-12").suggestions[n]


def test_deciding_through_the_approvals_api_updates_the_analysis_with_the_signed_in_reviewer(api, monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    target = _suggestion(api.db)
    r = api.client.post(f"/api/approvals/{target.approval_id}/decide", headers={**H, "Authorization": "Bearer alice"},
                        json={"answer": "yes", "reviewer": "someone-else"})  # (a body reviewer is ignored)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "accepted" and body["decided_by"] == "alice" and body["reviewer"] == "alice"
    after = _suggestion(api.db)
    assert after.review.value == "accepted" and after.reviewer == "alice"
    history = store.analysis_history(api.db, "t1", "SHOP-12")
    assert any("accepted by alice" in h["event"] for h in history)
    # the other tenant's copy of the same requirement is untouched
    assert _suggestion(api.db, "t2").review.value == "needs_review"


def test_a_rejection_in_the_queue_is_a_rejection_in_the_analysis(api, monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    target = _suggestion(api.db, n=1)
    r = api.client.post(f"/api/approvals/{target.approval_id}/decide", headers={**H, "Authorization": "Bearer alice"},
                        json={"answer": "no"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert _suggestion(api.db, n=1).review.value == "rejected"


def test_another_tenant_cannot_decide_a_suggestion(api, monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    target = _suggestion(api.db)
    r = api.client.post(f"/api/approvals/{target.approval_id}/decide", headers={**H, "Authorization": "Bearer bob"},
                        json={"answer": "yes"})
    assert r.status_code == 403
    assert approvals.get_approval(target.approval_id)["status"] == "pending"
    assert _suggestion(api.db).review.value == "needs_review"


def test_a_viewer_cannot_decide_and_a_shared_token_cannot_sign_a_review(api, monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    target = _suggestion(api.db)
    r = api.client.post(f"/api/approvals/{target.approval_id}/decide",
                        headers={**H, "Authorization": "Bearer viewer-1"}, json={"answer": "yes"})
    assert r.status_code == 403
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "bearer")
    monkeypatch.setenv("QPILOT_DASHBOARD_TOKEN", "shared-dashboard-token-123")
    r = api.client.post(f"/api/approvals/{target.approval_id}/decide",
                        headers={**H, "Authorization": "Bearer shared-dashboard-token-123"}, json={"answer": "yes"})
    assert r.status_code == 403 and "named, signed-in person" in r.json()["detail"]
    assert approvals.get_approval(target.approval_id)["status"] == "pending"


def test_with_studio_login_off_the_decision_is_recorded_as_the_local_user(api, monkeypatch):
    monkeypatch.delenv("QPILOT_DASHBOARD_AUTH", raising=False)
    monkeypatch.delenv("QPILOT_DASHBOARD_TOKEN", raising=False)
    target = _suggestion(api.db)
    r = api.client.post(f"/api/approvals/{target.approval_id}/decide", headers=H, json={"answer": "yes"})
    assert r.status_code == 200, r.text
    assert r.json()["decided_by"] == "local-user" and _suggestion(api.db).reviewer == "local-user"


def test_requirement_suggestions_cannot_be_made_up_through_the_api(api, monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    detail = json.dumps({"requirement": "SHOP-12", "suggestion": "SHOP-12#S-1"})
    r = api.client.post("/api/approvals", headers={**H, "Authorization": "Bearer alice"},
                        json={"kind": "requirement_suggestion", "subject": "fake", "detail": detail})
    assert r.status_code == 400
    assert not [a for a in approvals.list_approvals(status="all") if a["subject"] == "fake"]


def test_a_forged_queue_row_cannot_decide_a_real_suggestion(api, monkeypatch):
    """A row made directly in the queue (not by analyze) that names a real suggestion is refused."""
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    forged = approvals.create("requirement_suggestion", "forged", tenant_id="t1",
                              detail=json.dumps({"requirement": "SHOP-12", "suggestion": "SHOP-12#S-1"}))
    r = api.client.post(f"/api/approvals/{forged['id']}/decide", headers={**H, "Authorization": "Bearer alice"},
                        json={"answer": "yes"})
    assert r.status_code == 403
    assert _suggestion(api.db).review.value == "needs_review"
    assert approvals.get_approval(forged["id"])["status"] == "pending"


def test_the_queue_refuses_an_unnamed_decision_of_a_suggestion(api):
    target = _suggestion(api.db)
    with pytest.raises(PermissionError):
        approvals.decide_approval(target.approval_id, "yes")
    assert approvals.get_approval(target.approval_id)["status"] == "pending"


def test_other_approval_kinds_still_work_as_before(api, monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    made = api.client.post("/api/approvals", headers={**H, "Authorization": "Bearer alice"},
                           json={"kind": "sensitive", "subject": "delete the account"})
    assert made.status_code == 200
    r = api.client.post(f"/api/approvals/{made.json()['id']}/decide", headers={**H, "Authorization": "Bearer alice"},
                        json={"answer": "yes"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"


# ---------------------------------------------------------------- 6 the read-only command line

@pytest.fixture
def run_cli(mock, tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_READ_API_TOKEN", TOKEN)
    monkeypatch.setattr(audit_store, "DEFAULT_DB", tmp_path / "audit.sqlite")
    for key in ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT"):
        monkeypatch.delenv(key, raising=False)

    def run(*argv):
        lines = []
        code = cli.run(["--db", str(tmp_path / "req.sqlite"), "--tenant", "t1", "--base-url", mock.url, *argv],
                       out=lines.append)
        return code, "\n".join(lines)
    return run


def test_cli_check_connect_types_sync_show_and_analyze(run_cli, mock):
    _add(mock, "SHOP-2", "Task", "As a shopper.\nAC1: Valid login opens the dashboard\nAC2: A wrong password shows "
                                 "an error\nNotes: see Figma")
    code, text = run_cli("check", "--site", SITE, "--email", EMAIL)
    assert code == 0 and "account: QA Reader" in text and "read_only: True" in text and TOKEN not in text
    assert EMAIL not in text.replace(f"email: {EMAIL}", "")
    code, text = run_cli("connect", "--id", "jira-main", "--site", SITE, "--email", EMAIL)
    assert code == 0 and "saved: jira-main" in text
    code, text = run_cli("types", "--connection", "jira-main", "--project", "SHOP")
    assert code == 0 and "* Story" in text and "Task                 1 items" in text
    code, text = run_cli("sync", "--connection", "jira-main", "--project", "SHOP")
    assert code == 0 and "WARNING: 0 work items imported from SHOP (types: Story)" in text and "Task (1)" in text
    code, text = run_cli("sync", "--connection", "jira-main", "--project", "SHOP", "--types", "Task", "--full")
    assert code == 0 and "new: 1" in text and "WARNING" not in text
    code, text = run_cli("show", "--connection", "jira-main", "SHOP-2")
    assert code == 0 and "AC-1: Valid login opens the dashboard" in text and "AC-2: A wrong password shows an error" \
        in text and "see Figma" not in text.split("acceptance criteria")[1]
    code, text = run_cli("--json", "analyze", "--connection", "jira-main", "SHOP-2")
    assert code == 0 and len(json.loads(text)["criteria"]) == 2
    assert {r["method"] for r in mock.requests} <= {"GET", "POST"}
    assert {r["path"] for r in mock.requests if r["method"] == "POST"} <= {
        "/rest/api/3/search/jql", "/rest/api/3/search/approximate-count"}


def test_cli_never_takes_a_token_value_and_reports_auth_errors_without_it(run_cli, mock, monkeypatch):
    code, text = run_cli("check", "--site", SITE, "--email", EMAIL, "--token-env", "ATATT3xFfGF0abcdefghijklmnop")
    assert code == 1 and "ATATT3xFfGF0abcdefghijklmnop" not in text and "error:" in text
    code, text = run_cli("check", "--site", SITE, "--email", EMAIL, "--token-env", "JIRA_API_TOKEN")
    assert code == 1 and "older Jira defect creation" in text
    monkeypatch.setenv("JIRA_READ_API_TOKEN", "a-wrong-token-value-4471")
    code, text = run_cli("check", "--site", SITE, "--email", EMAIL)
    assert code == 1 and "auth_expired" in text and "a-wrong-token-value-4471" not in text
    monkeypatch.delenv("JIRA_READ_API_TOKEN")
    code, text = run_cli("check", "--site", SITE, "--email", EMAIL)
    assert code == 1 and "auth_missing" in text


def test_cli_refuses_non_cloud_sites_and_warns_when_the_defect_creation_would_write(run_cli, monkeypatch):
    code, text = run_cli("check", "--site", "https://jira.example.com", "--email", EMAIL)
    assert code == 1 and "atlassian.net" in text
    for key, value in {"JIRA_URL": SITE, "JIRA_EMAIL": EMAIL, "JIRA_API_TOKEN": "legacy-token-value-1",
                       "JIRA_PROJECT": "QPL"}.items():
        monkeypatch.setenv(key, value)
    code, text = run_cli("check", "--site", SITE, "--email", EMAIL)
    assert code == 0 and "CREATE Bug issues in QPL" in text and "legacy-token-value-1" not in text


def test_cli_works_for_the_qpl_site_address_and_key(run_cli, mock):
    mock.projects = [{"id": "7", "key": "QPL", "name": "Qpilot"}]
    _add(mock, "QPL-2", "Story", "Acceptance Criteria\n- User can log in with a valid email and password")
    site = "https://aimaniforall1234-1795449805793.atlassian.net"
    assert run_cli("connect", "--id", "qpl", "--site", site, "--email", EMAIL)[0] == 0
    code, text = run_cli("sync", "--connection", "qpl", "--project", "QPL")
    assert code == 0 and "new: 1" in text
    code, text = run_cli("show", "--connection", "qpl", "QPL-2")
    assert f"link: {site}/browse/QPL-2" in text and "AC-1: User can log in with a valid email and password" in text
