"""Requirements Intelligence, Milestone 2: import modes (incremental, full, targeted), filters, preview, results and
history in backend/atlassian/sync.py, and the Studio API (backend/requirements_api.py) with its login, roles,
tenants and token handling. Everything runs against tests/atlassian_mock.py on 127.0.0.1."""
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest

from backend import approvals, audit_store, requirements_api as rapi
from backend.atlassian import analysis as an, credentials, jira, store, sync
from backend.atlassian.client import Client
from backend.atlassian.models import Connection, ImportFilter
from tests.atlassian_mock import EMAIL, T0, TOKEN, MockJira, story

SITE = "https://acme-test.atlassian.net"
AC = "Acceptance Criteria\n- Valid login opens the dashboard\n- A wrong password shows an error"


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


def add(mock, key, type_name="Story", description=AC, minutes=0, **fields):
    mock.issues[key] = story(key, f"{type_name} {key}", T0 + timedelta(minutes=minutes), description, "",
                             issuetype={"name": type_name}, **fields)


def audit_path(db) -> Path:
    return Path(db.execute("PRAGMA database_list").fetchone()[2]).with_name("audit.sqlite")


def run(db, mock, mode, c=None, **kw):
    c = c or conn()
    store.save_connection(db, c)
    return sync.run_import(db, c, client(mock, c), tenant_id=c.tenant_id, mode=mode, audit_db=audit_path(db), **kw)


# ================================================================ 1 filters, keys and links (unit)

def test_every_filter_becomes_quoted_jql():
    f = ImportFilter(project="QPL", epic="QPL-1", sprint="open", statuses=["To Do", 'In "Review"'],
                     priorities=["High"], assignee="me", labels=["checkout"], created_from="2026-01-01",
                     created_to="2026-01-31", updated_from="2026-11-01", text='log "in"', jql="component = Web")
    assert jira.filter_jql(f) == (
        'parent = QPL-1 AND sprint in openSprints() AND status in ("To Do", "In \\"Review\\"") AND '
        'priority in ("High") AND assignee = currentUser() AND labels in ("checkout") AND created >= "2026/01/01" '
        'AND created < "2026/02/01" AND updated >= "2026/11/01" AND summary ~ "log \\"in\\"" AND (component = Web)')
    assert jira.filter_jql(ImportFilter(project="QPL", sprint="42", assignee="unassigned")) == \
        "sprint = 42 AND assignee is EMPTY"
    assert jira.filter_jql(ImportFilter(project="QPL", sprint="Sprint 7", assignee="5b10ac8d82e05b22cc7d4ef5")) == \
        'sprint = "Sprint 7" AND assignee = "5b10ac8d82e05b22cc7d4ef5"'


@pytest.mark.parametrize("bad", [{"epic": "not a key"}, {"assignee": "bob smith"}, {"created_from": "2026-13-01"},
                                 {"updated_to": "01/02/2026"}, {"jql": "status = Done ORDER BY key"},
                                 {"jql": "project = OTHER"}, {"jql": "project in (A, B)"}, {"text": "a\x00b"},
                                 {"statuses": ["x\ny"]}, {"project": "qpl"}, {"sprint": "a\tb"}])
def test_invalid_filters_are_refused(bad):
    with pytest.raises(ValueError):
        ImportFilter(**{"project": "QPL", **bad})


@pytest.mark.parametrize("escape", ["status = Done) OR (key = OTHER-1", "a = 1) OR (b = 2", 'summary ~ "x'])
def test_a_jql_filter_cannot_step_out_of_its_brackets(escape):
    with pytest.raises(ValueError):
        jira.filter_jql(ImportFilter(project="QPL", jql=escape))
    with pytest.raises(ValueError):
        jira.build_jql("QPL", ["Story"], escape)


def test_keys_and_work_item_links_are_read():
    host = "acme-test.atlassian.net"
    assert jira.parse_issue_refs("QPL-2", host) == ["QPL-2"]
    assert jira.parse_issue_refs("qpl-2, QPL-3;QPL-2  QPL-10", host) == ["QPL-2", "QPL-3", "QPL-10"]
    assert jira.parse_issue_refs(f"{SITE}/browse/QPL-5", host) == ["QPL-5"]
    assert jira.parse_issue_refs(f"{SITE}/jira/software/projects/QPL/boards/1?selectedIssue=QPL-6", host) == ["QPL-6"]
    assert jira.parse_issue_refs(f"{SITE}/jira/software/c/projects/QPL/issues/QPL-4?filter=all", host) == ["QPL-4"]


@pytest.mark.parametrize("bad", ["https://other-site.atlassian.net/browse/QPL-2", "http://acme-test.atlassian.net/browse/QPL-2",
                                 "https://acme-test.atlassian.net/wiki/spaces/ENG", "QPL", "QPL-0", "DROP TABLE",
                                 ",".join(f"QPL-{i}" for i in range(1, 202))])
def test_links_to_other_sites_and_non_keys_are_refused(bad):
    with pytest.raises(ValueError):
        jira.parse_issue_refs(bad, "acme-test.atlassian.net")


def test_jql_is_validated_by_jira_through_a_read_only_call(mock):
    c = client(mock)
    assert jira.validate_jql(c, "project = SHOP AND status = Done") == []
    assert jira.validate_jql(c, "project = SHOP AND BAD") != []
    assert mock.requests[-1]["method"] == "POST" and mock.requests[-1]["path"] == "/rest/api/3/jql/parse"


# ================================================================ 2 incremental synchronization

def test_incremental_import_reports_new_changed_unchanged_and_what_needs_analysis(mock, db):
    add(mock, "SHOP-1")
    add(mock, "SHOP-2", minutes=1)
    first = run(db, mock, "incremental", filters=ImportFilter(project="SHOP"))
    assert first["status"] == "complete" and first["new_keys"] == ["SHOP-1", "SHOP-2"]
    assert first["criteria_extracted"] == {"SHOP-1": 2, "SHOP-2": 2}
    assert first["needs_analysis"] == ["SHOP-1", "SHOP-2"] and first["duration_s"] >= 0
    an.analyze(db, "t1", "jira-main:jira_issue:SHOP-1", approvals_db=audit_path(db).with_name("ap.sqlite"),
               audit_db=audit_path(db))
    mock.touch("SHOP-1", T0 + timedelta(days=30), summary="Login, reworded")
    second = run(db, mock, "incremental", filters=ImportFilter(project="SHOP"))
    assert second["changed_keys"] == ["SHOP-1"] and second["new_keys"] == []
    assert second["unchanged"] >= 0 and second["new"] == 0
    assert [a["requirement"] for a in second["affected"]] == ["SHOP-1"]
    assert "version 1 -> 2" in second["affected"][0]["reasons"][0]
    assert second["last_success"] == second["finished_at"]
    # versions kept, no duplicate rows
    assert [v["source"].version for v in store.history(db, "t1", "jira-main:jira_issue:SHOP-1")] == [1, 2]
    assert len(store.list_sources(db, "t1")) == 2


def test_an_interrupted_import_resumes_from_its_cursor(mock, db):
    for i in range(1, 8):
        add(mock, f"SHOP-{i}", minutes=i)
    c = conn()
    store.save_connection(db, c)
    stops = iter([False, True])
    first = sync.sync_jira(db, c, client(mock, c), tenant_id="t1", project="SHOP", page_size=3,
                           audit_db=audit_path(db), should_stop=lambda: next(stops, False))
    assert first["status"] == "cancelled" and first["new"] == 6
    again = sync.sync_jira(db, c, client(mock, c), tenant_id="t1", project="SHOP", page_size=3,
                           audit_db=audit_path(db))
    assert again["resumed"] and again["status"] == "complete" and again["new"] == 1
    assert len(store.list_sources(db, "t1")) == 7


# ================================================================ 3 full synchronization

def test_full_import_of_every_work_item_type_and_missing_items_keep_their_history(mock, db):
    for i, t in enumerate(["Story", "Task", "Bug", "Epic", "Subtask", "User Story"], 1):
        add(mock, f"SHOP-{i}", t, minutes=i)
    c = conn(work_item_types=["Story", "Task", "Bug", "Epic", "Subtask", "User Story"])
    full = run(db, mock, "full", c, filters=ImportFilter(project="SHOP"))
    assert full["new"] == 6 and full["warnings"] == []
    del mock.issues["SHOP-3"]
    again = run(db, mock, "full", c, filters=ImportFilter(project="SHOP"))
    assert again["missing"] == ["jira-main:jira_issue:SHOP-3"] and again["unchanged"] == 5
    kept = store.get_source(db, "t1", "jira-main:jira_issue:SHOP-3")
    assert kept and kept["present"] is False and len(store.history(db, "t1", "jira-main:jira_issue:SHOP-3")) == 1


def test_filters_narrow_the_import_and_keep_their_own_cursor(mock, db):
    add(mock, "SHOP-1", status={"name": "Done"}, labels=["checkout"])
    add(mock, "SHOP-2", minutes=1, status={"name": "To Do"}, labels=["checkout"])
    add(mock, "SHOP-3", minutes=2, status={"name": "Done"}, labels=["login"])
    narrow = run(db, mock, "full", filters=ImportFilter(project="SHOP", statuses=["Done"], labels=["checkout"]))
    assert narrow["new_keys"] == ["SHOP-1"]
    assert 'status in ("Done")' in narrow["scope"] and 'labels in ("checkout")' in narrow["scope"]
    whole = run(db, mock, "full", filters=ImportFilter(project="SHOP"))
    assert whole["new_keys"] == ["SHOP-2", "SHOP-3"]  # (its own scope: SHOP-1 is unchanged, not new)
    # a later narrowed full import does not mark the rest of the project missing
    assert run(db, mock, "full", filters=ImportFilter(project="SHOP", statuses=["Done"],
                                                      labels=["checkout"]))["missing"] == []
    assert all(r["present"] for r in store.list_sources(db, "t1"))


def test_epic_filter_reads_the_epics_children(mock, db):
    add(mock, "SHOP-1", "Epic")
    add(mock, "SHOP-2", minutes=1, parent={"key": "SHOP-1"})
    add(mock, "SHOP-3", minutes=2)
    result = run(db, mock, "full", filters=ImportFilter(project="SHOP", epic="SHOP-1"))
    assert result["new_keys"] == ["SHOP-2"] and "parent = SHOP-1" in result["scope"]


# ================================================================ 4 specific work items

def test_targeted_import_reads_only_the_selected_items(mock, db):
    for i in range(1, 6):
        add(mock, f"SHOP-{i}", minutes=i)
    result = run(db, mock, "items", keys=["SHOP-2", "SHOP-4"])
    assert result["status"] == "complete" and result["new_keys"] == ["SHOP-2", "SHOP-4"]
    assert sorted(r["source"].source_id for r in store.list_sources(db, "t1")) == ["SHOP-2", "SHOP-4"]
    assert all(r["method"] == "GET" for r in mock.requests if "/issue/" in r["path"])


def test_a_targeted_import_never_disturbs_the_project_scope(mock, db):
    for i in range(1, 4):
        add(mock, f"SHOP-{i}", minutes=i)
    run(db, mock, "full", filters=ImportFilter(project="SHOP"))
    scope = 'jql:project = SHOP AND issuetype in ("Story") ORDER BY updated ASC, key ASC'
    before = store.load_cursor(db, "t1", "jira-main", scope)
    mock.touch("SHOP-2", T0 + timedelta(days=9), summary="Changed")
    targeted = run(db, mock, "items", keys=["SHOP-2"])
    assert targeted["changed_keys"] == ["SHOP-2"] and targeted["missing"] == []
    assert store.load_cursor(db, "t1", "jira-main", scope) == before  # (the project cursor is untouched)
    row = db.execute("SELECT scope FROM sources WHERE source_key = 'jira-main:jira_issue:SHOP-2'").fetchone()
    assert row["scope"] == scope  # (still the project's: its full sync still checks it)
    del mock.issues["SHOP-3"]
    assert run(db, mock, "full", filters=ImportFilter(project="SHOP"))["missing"] == ["jira-main:jira_issue:SHOP-3"]


def test_an_inaccessible_requested_item_is_reported_and_only_it_is_marked_missing(mock, db):
    add(mock, "SHOP-1")
    add(mock, "SHOP-2", minutes=1)
    run(db, mock, "items", keys=["SHOP-1", "SHOP-2"])
    del mock.issues["SHOP-1"]
    result = run(db, mock, "items", keys=["SHOP-1", "SHOP-9"])
    assert result["status"] == "partial"
    assert result["inaccessible"] == ["SHOP-1: not_found", "SHOP-9: not_found"] and result["missing"] == ["SHOP-1"]
    assert store.get_source(db, "t1", "jira-main:jira_issue:SHOP-2")["present"] is True


def test_targeted_import_can_follow_subtasks_parent_and_linked_items(mock, db):
    add(mock, "SHOP-1", "Epic")
    add(mock, "SHOP-2", minutes=1, parent={"key": "SHOP-1"},
        issuelinks=[{"type": {"outward": "blocks", "inward": "is blocked by"}, "outwardIssue": {"key": "SHOP-4"}}])
    add(mock, "SHOP-3", "Subtask", minutes=2, parent={"key": "SHOP-2"})
    add(mock, "SHOP-4", minutes=3)
    add(mock, "SHOP-5", minutes=4)
    only = run(db, mock, "items", keys=["SHOP-2"])
    assert only["new_keys"] == ["SHOP-2"]
    result = run(db, mock, "items", keys=["SHOP-2"], include=("subtasks", "parent", "linked"))
    assert sorted(result["new_keys"]) == ["SHOP-1", "SHOP-3", "SHOP-4"]
    assert "SHOP-5" not in {r["source"].source_id for r in store.list_sources(db, "t1")}
    related = {x["to_key"].split(":")[-1]: x["found_via"] for x in
               store.links_from(db, "t1", "jira-main:jira_issue:SHOP-2")}
    assert related == {"SHOP-1": "parent of SHOP-2", "SHOP-3": "sub-task of SHOP-2", "SHOP-4": "blocks SHOP-2"}


def test_an_unknown_include_is_refused(mock, db):
    with pytest.raises(ValueError):
        run(db, mock, "items", keys=["SHOP-1"], include=("everything",))


# ================================================================ 5 preview

def test_preview_lists_new_updated_and_unchanged_without_storing_anything(mock, db):
    for i in range(1, 4):
        add(mock, f"SHOP-{i}", minutes=i)
    run(db, mock, "items", keys=["SHOP-1", "SHOP-2"])
    mock.touch("SHOP-2", T0 + timedelta(days=4), summary="Edited")
    before = store.list_sources(db, "t1")
    c = conn()
    view = sync.preview(db, c, client(mock, c), tenant_id="t1", filters=ImportFilter(project="SHOP"),
                        audit_db=audit_path(db))
    states = {i["key"]: i["state"] for i in view["items"]}
    assert states == {"SHOP-1": "unchanged", "SHOP-2": "updated", "SHOP-3": "new"}
    assert view["estimated_total"] == 3 and view["counts"] == {"new": 1, "updated": 1, "unchanged": 1,
                                                                 "reappeared": 0}
    assert view["items"][0]["summary"] and view["items"][0]["type"] == "Story"
    assert store.list_sources(db, "t1") == before


def test_preview_of_keys_and_of_a_page(mock, db):
    for i in range(1, 6):
        add(mock, f"SHOP-{i}", minutes=i)
    c = conn()
    keyed = sync.preview(db, c, client(mock, c), tenant_id="t1", keys=["SHOP-3", "SHOP-8"], audit_db=audit_path(db))
    assert [i["key"] for i in keyed["items"]] == ["SHOP-3"] and keyed["inaccessible"] == ["SHOP-8: not_found"]
    paged = sync.preview(db, c, client(mock, c), tenant_id="t1", filters=ImportFilter(project="SHOP"), limit=2,
                         audit_db=audit_path(db))
    assert len(paged["items"]) == 2 and paged["next_page_token"]
    rest = sync.preview(db, c, client(mock, c), tenant_id="t1", filters=ImportFilter(project="SHOP"), limit=2,
                        next_page_token=paged["next_page_token"], audit_db=audit_path(db))
    assert [i["key"] for i in rest["items"]] == ["SHOP-3", "SHOP-4"]


# ================================================================ 6 history

def test_every_import_is_kept_in_the_sync_history(mock, db):
    add(mock, "SHOP-1")
    run(db, mock, "full", filters=ImportFilter(project="SHOP"))
    run(db, mock, "items", keys=["SHOP-1", "SHOP-7"])
    runs = store.sync_runs(db, "t1")
    assert [r["mode"] for r in runs] == ["items", "full"] and [r["status"] for r in runs] == ["partial", "complete"]
    assert runs[1]["result"]["new_keys"] == ["SHOP-1"]
    assert store.last_success(db, "t1", "jira-main") == runs[1]["finished_at"]
    assert store.sync_runs(db, "t2") == []


# ================================================================ 7 the Studio API

@pytest.fixture
def api(monkeypatch, tmp_path, mock):
    from fastapi.testclient import TestClient

    import backend.tenancy_store as tenancy
    from backend import server
    monkeypatch.setattr(approvals, "DEFAULT_DB", tmp_path / "approvals.sqlite")
    monkeypatch.setattr(store, "DEFAULT_DB", tmp_path / "req.sqlite")
    monkeypatch.setattr(audit_store, "DEFAULT_DB", tmp_path / "audit.sqlite")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", tmp_path / "tenancy.sqlite")
    monkeypatch.setattr(credentials, "DEFAULT_FILE", tmp_path / "creds.json")
    monkeypatch.setattr(rapi, "CLIENT_BASE_URL", mock.url)
    monkeypatch.setattr(rapi, "JOBS", rapi.Jobs())
    for key in ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT", "JIRA_READ_API_TOKEN",
                "QPILOT_DASHBOARD_AUTH", "QPILOT_DASHBOARD_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    tenancy.upsert_tenant("t1", "One")
    tenancy.upsert_tenant("t2", "Two")
    for who, tenant, role in (("admin-1", "t1", "admin"), ("op-1", "t1", "operator"), ("view-1", "t1", "viewer"),
                              ("admin-2", "t2", "admin")):
        tenancy.upsert_principal(who, tenant, f"{who}@ex.test", role)
    for i, t in enumerate(["Story", "Story", "Task"], 1):
        add(mock, f"SHOP-{i}", t, minutes=i)
    return TestClient(server.app, base_url="http://127.0.0.1:8000")


H = {"X-Agentic-QA": "1"}


def as_(who):
    return {**H, "Authorization": f"Bearer {who}"}


CONN = {"id": "jira-main", "product": "jira", "site_url": SITE, "email": EMAIL, "work_item_types": ["Story", "Task"]}


def wait_job(api, job, headers=H):
    rapi.JOBS.wait(job["id"])
    r = api.get(f"/api/requirements/imports/{job['id']}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_local_studio_end_to_end_from_connection_to_review(api, mock):
    caps = api.get("/api/requirements/capabilities").json()
    assert caps["capabilities"]["import_requirements"] and not caps["capabilities"]["generate_test_cases"]
    assert caps["coming"]["run_selected_tests"].startswith("Phase 4") and caps["actor"] == "local-user"
    saved = api.post("/api/requirements/connections", headers=H, json=CONN)
    assert saved.status_code == 200 and saved.json()["token_ref"] == "JIRA_READ_API_TOKEN"
    assert saved.json()["credential"]["configured"] is False
    r = api.post("/api/requirements/connections/jira-main/test", headers=H)
    assert r.status_code == 412 and r.json()["detail"]["kind"] == "auth_missing"
    r = api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    assert r.status_code == 200 and r.json()["credential"] == {**r.json()["credential"], "configured": True,
                                                                "source": "studio"}
    assert TOKEN not in r.text
    r = api.post("/api/requirements/connections/jira-main/test", headers=H)
    assert r.status_code == 200 and r.json()["account"] == "QA Reader" and r.json()["read_only"] is True
    assert api.get("/api/requirements/connections/jira-main/projects").json()["projects"][0]["key"] == "SHOP"
    types = api.get("/api/requirements/connections/jira-main/projects/SHOP/types").json()["types"]
    assert {t["name"]: (t["count"], t["selected"]) for t in types}["Task"] == (1, True)
    pv = api.post("/api/requirements/connections/jira-main/preview", headers=H,
                  json={"filters": {"project": "SHOP"}}).json()
    assert pv["counts"]["new"] == 3 and pv["estimated_total"] == 3
    job = api.post("/api/requirements/connections/jira-main/imports", headers=H,
                   json={"mode": "items", "keys": f"SHOP-1, {SITE}/browse/SHOP-3"}).json()
    done = wait_job(api, job)
    assert done["status"] == "complete" and done["result"]["new_keys"] == ["SHOP-1", "SHOP-3"]
    listing = api.get("/api/requirements/items?sort=-key").json()
    assert [i["key"] for i in listing["items"]] == ["SHOP-3", "SHOP-1"] and listing["items"][0]["criteria"] == 2
    assert listing["items"][0]["analysis"] == "not_analyzed" and listing["items"][0]["type"] == "Task"
    assert api.get("/api/requirements/items?type=Task").json()["total"] == 1
    assert api.get("/api/requirements/items?q=story%20shop-1").json()["total"] == 1
    assert api.get("/api/requirements/items?q=no-such-words").json()["total"] == 0
    detail = api.get("/api/requirements/items/jira-main/SHOP-1").json()
    assert [c["text"] for c in detail["criteria"]] == ["Valid login opens the dashboard",
                                                       "A wrong password shows an error"]
    assert detail["criteria"][0]["citation"]["version"] == 1 and detail["requirement_kind"] == "story"
    assert api.get("/api/requirements/items/jira-main/SHOP-1/versions").json()["versions"][0]["version"] == 1
    analysed = api.post("/api/requirements/items/jira-main/SHOP-1/analyze", headers=H, json={"ai": "off"}).json()
    sid = analysed["analysis"]["suggestions"][0]["id"]
    r = api.post(f"/api/requirements/items/jira-main/SHOP-1/suggestions/{quote(sid, safe='')}/review", headers=H,
                 json={"answer": "yes"})
    assert r.status_code == 200 and r.json()["suggestion"]["reviewer"] == "local-user"
    assert approvals.get_approval(r.json()["suggestion"]["approval_id"])["decided_by"] == "local-user"
    ov = api.get("/api/requirements/overview").json()
    assert ov["requirements"] == 2 and ov["analysed"] == 1 and ov["criteria"] == 2
    assert ov["pending_reviews"] == len(analysed["analysis"]["suggestions"]) - 1
    assert api.get("/api/requirements/coverage").json()["requirements"][0]["requirement"] == "SHOP-1"
    history = api.get("/api/requirements/imports").json()["runs"]
    assert history[0]["mode"] == "items" and history[0]["status"] == "complete"
    actions = {e["action"] for e in api.get("/api/requirements/audit").json()["events"]}
    assert {"requirements.connection.save", "requirements.token.set", "requirements.import.start"} <= actions
    assert not [r for r in mock.requests if r["method"] not in ("GET", "POST")]


def test_incremental_and_full_imports_and_a_cancel_through_the_api(api, mock):
    api.post("/api/requirements/connections", headers=H, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    body = {"mode": "full", "filters": {"project": "SHOP"}}
    done = wait_job(api, api.post("/api/requirements/connections/jira-main/imports", headers=H, json=body).json())
    assert done["result"]["new"] == 3 and done["progress"]["pages"] == 1
    mock.touch("SHOP-2", datetime.now(UTC) + timedelta(minutes=5), summary="Edited")  # (after the last import)
    inc = wait_job(api, api.post("/api/requirements/connections/jira-main/imports", headers=H,
                                 json={"mode": "incremental", "filters": {"project": "SHOP"}}).json())
    assert inc["result"]["changed_keys"] == ["SHOP-2"] and inc["result"]["mode"] == "incremental"
    job = api.post("/api/requirements/connections/jira-main/imports", headers=H, json=body).json()
    r = api.post(f"/api/requirements/imports/{job['id']}/cancel", headers=H)
    assert r.status_code == 200
    assert wait_job(api, job)["status"] in ("cancelled", "complete")  # (a one-page import may finish first)


def test_bad_requests_get_meaningful_answers(api):
    api.post("/api/requirements/connections", headers=H, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    url = "/api/requirements/connections/jira-main"
    r = api.post(f"{url}/imports", headers=H, json={"mode": "items", "keys": "https://evil.atlassian.net/browse/X-1"})
    assert r.status_code == 400 and "not a link to acme-test.atlassian.net" in r.json()["detail"]["message"]
    r = api.post(f"{url}/imports", headers=H, json={"mode": "full", "filters": {"project": "SHOP", "jql": "BAD"}})
    assert r.status_code == 400 and "Jira refused the JQL filter" in r.json()["detail"]["message"]
    r = api.post(f"{url}/jql/validate", headers=H, json={"project": "SHOP", "jql": "status = Done"})
    assert r.json()["valid"] is True and r.json()["jql"].startswith("project = SHOP")
    r = api.post(f"{url}/jql/validate", headers=H, json={"project": "SHOP", "jql": "a) OR (b"})
    assert r.json()["valid"] is False
    r = api.post(f"{url}/imports", headers=H, json={"mode": "full"})
    assert r.status_code == 400 and "choose a project" in r.json()["detail"]["message"]
    assert api.post(f"{url}/imports", headers=H, json={"mode": "delete-all"}).status_code == 422
    r = api.post("/api/requirements/connections", headers=H, json={**CONN, "site_url": "https://jira.example.com"})
    assert r.status_code == 400 and "atlassian.net" in r.json()["detail"]
    r = api.post("/api/requirements/connections", headers=H, json={**CONN, "token_ref": "JIRA_API_TOKEN"})
    assert r.status_code == 400 and "defect creation" in r.json()["detail"]
    r = api.post("/api/requirements/connections", headers=H, json={**CONN, "token_ref": "ATATT3xFfGF0abcdefghijklmn"})
    assert r.status_code == 400 and "ATATT3xFfGF0abcdefghijklmn" not in r.text
    api.put(f"{url}/token", headers=H, json={"token": "a-revoked-token-value-551"})
    r = api.post(f"{url}/test", headers=H)
    assert r.status_code == 424 and r.json()["detail"]["kind"] == "auth_expired" and "replace it" in r.text
    assert "a-revoked-token-value-551" not in r.text
    assert api.put(f"{url}/token", headers=H, json={"token": "has space"}).status_code == 400
    assert api.post("/api/requirements/connections", json=CONN).status_code == 403  # (no X-Agentic-QA header)


def test_tokens_never_leave_the_server(api, tmp_path, mock):
    api.post("/api/requirements/connections", headers=H, json=CONN)
    secret = "never-show-this-token-7781"
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": secret})
    bodies = [api.get(p).text for p in ("/api/requirements/connections", "/api/requirements/overview",
                                        "/api/requirements/audit", "/api/requirements/imports",
                                        "/api/requirements/capabilities")]
    bodies.append(api.post("/api/requirements/connections/jira-main/test", headers=H).text)
    assert not [b for b in bodies if secret in b]
    assert secret not in (tmp_path / "audit.sqlite").read_bytes().decode("utf-8", "replace")
    assert secret not in (tmp_path / "req.sqlite").read_bytes().decode("utf-8", "replace")
    creds = tmp_path / "creds.json"
    if os.name != "nt":
        assert stat.S_IMODE(creds.stat().st_mode) == 0o600
    from backend.safety import redact
    assert redact(f"oops {secret}") == "oops [REDACTED]"
    r = api.delete("/api/requirements/connections/jira-main/token", headers=H)
    assert r.json()["removed"] is True and r.json()["credential"]["configured"] is False


def test_the_local_tenant_may_use_dotenv_but_other_tenants_never_use_the_servers_token(api, monkeypatch):
    monkeypatch.setenv("JIRA_READ_API_TOKEN", TOKEN)
    api.post("/api/requirements/connections", headers=H, json=CONN)
    r = api.post("/api/requirements/connections/jira-main/test", headers=H)
    assert r.status_code == 200
    assert api.get("/api/requirements/connections").json()["connections"][0]["credential"]["source"] == "environment"
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    api.post("/api/requirements/connections", headers=as_("admin-1"), json=CONN)
    r = api.post("/api/requirements/connections/jira-main/test", headers=as_("admin-1"))
    assert r.status_code == 412 and r.json()["detail"]["kind"] == "auth_missing"


def test_roles_decide_what_each_person_may_do(api, monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    assert api.get("/api/requirements/connections").status_code == 401
    assert api.post("/api/requirements/connections", headers=as_("op-1"), json=CONN).status_code == 403
    assert api.post("/api/requirements/connections", headers=as_("view-1"), json=CONN).status_code == 403
    assert api.post("/api/requirements/connections", headers=as_("admin-1"), json=CONN).status_code == 200
    assert api.put("/api/requirements/connections/jira-main/token", headers=as_("op-1"),
                   json={"token": TOKEN}).status_code == 403
    assert api.put("/api/requirements/connections/jira-main/token", headers=as_("admin-1"),
                   json={"token": TOKEN}).status_code == 200
    assert api.get("/api/requirements/connections", headers=as_("view-1")).status_code == 200
    body = {"mode": "items", "keys": "SHOP-1"}
    assert api.post("/api/requirements/connections/jira-main/imports", headers=as_("view-1"),
                    json=body).status_code == 403
    job = api.post("/api/requirements/connections/jira-main/imports", headers=as_("op-1"), json=body)
    assert job.status_code == 200
    assert wait_job(api, job.json(), as_("op-1"))["status"] == "complete"
    assert api.post("/api/requirements/items/jira-main/SHOP-1/analyze", headers=as_("view-1"),
                    json={}).status_code == 403
    analysed = api.post("/api/requirements/items/jira-main/SHOP-1/analyze", headers=as_("op-1"), json={}).json()
    sid = analysed["analysis"]["suggestions"][0]["id"]
    url = f"/api/requirements/items/jira-main/SHOP-1/suggestions/{quote(sid, safe='')}/review"
    assert api.post(url, headers=as_("view-1"), json={"answer": "yes"}).status_code == 403
    r = api.post(url, headers=as_("op-1"), json={"answer": "no", "reviewer": "someone-else"})
    assert r.status_code == 200 and r.json()["suggestion"]["reviewer"] == "op-1"
    assert r.json()["suggestion"]["review"] == "rejected"
    assert api.get("/api/requirements/audit", headers=as_("op-1")).status_code == 403  # (audit.read: admin)
    assert api.get("/api/requirements/audit", headers=as_("admin-1")).status_code == 200


def test_one_tenant_never_sees_or_touches_another(api, monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    api.post("/api/requirements/connections", headers=as_("admin-1"), json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=as_("admin-1"), json={"token": TOKEN})
    job = api.post("/api/requirements/connections/jira-main/imports", headers=as_("admin-1"),
                   json={"mode": "items", "keys": "SHOP-1"}).json()
    wait_job(api, job, as_("admin-1"))
    other = as_("admin-2")
    assert api.get("/api/requirements/connections", headers=other).json()["connections"] == []
    assert api.get("/api/requirements/items", headers=other).json()["total"] == 0
    assert api.get("/api/requirements/items/jira-main/SHOP-1", headers=other).status_code == 404
    assert api.get(f"/api/requirements/imports/{job['id']}", headers=other).status_code == 404
    assert api.post(f"/api/requirements/imports/{job['id']}/cancel", headers=other).status_code == 404
    assert api.post("/api/requirements/connections/jira-main/test", headers=other).status_code == 404
    assert api.delete("/api/requirements/connections/jira-main", headers=other).status_code == 404
    assert api.get("/api/requirements/imports", headers=other).json()["runs"] == []
    assert api.get("/api/requirements/overview", headers=other).json()["requirements"] == 0
    assert all(e["tenant_id"] == "t2" for e in api.get("/api/requirements/audit", headers=other).json()["events"])
    # the same connection id in tenant 2 is a different connection, with no token
    api.post("/api/requirements/connections", headers=other, json=CONN)
    assert api.get("/api/requirements/connections", headers=other).json()["connections"][0]["credential"][
        "configured"] is False


def test_a_shared_token_can_import_but_cannot_sign_a_review(api, monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "bearer")
    monkeypatch.setenv("QPILOT_DASHBOARD_TOKEN", "shared-dashboard-token-123")
    h = as_("shared-dashboard-token-123")
    assert api.get("/api/requirements/connections", headers=as_("wrong")).status_code == 401
    api.post("/api/requirements/connections", headers=h, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=h, json={"token": TOKEN})
    wait_job(api, api.post("/api/requirements/connections/jira-main/imports", headers=h,
                           json={"mode": "items", "keys": "SHOP-1"}).json(), h)
    analysed = api.post("/api/requirements/items/jira-main/SHOP-1/analyze", headers=h, json={}).json()
    sid = analysed["analysis"]["suggestions"][0]["id"]
    r = api.post(f"/api/requirements/items/jira-main/SHOP-1/suggestions/{quote(sid, safe='')}/review", headers=h,
                 json={"answer": "yes"})
    assert r.status_code == 403 and "named, signed-in person" in r.json()["detail"]
    assert api.get("/api/requirements/capabilities", headers=h).json()["can_review"] is False


def test_disconnect_keeps_imported_requirements(api):
    api.post("/api/requirements/connections", headers=H, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    wait_job(api, api.post("/api/requirements/connections/jira-main/imports", headers=H,
                           json={"mode": "items", "keys": "SHOP-1"}).json())
    r = api.delete("/api/requirements/connections/jira-main", headers=H)
    assert r.json() == {"deleted": "jira-main", "imported_requirements_kept": True}
    assert api.get("/api/requirements/items").json()["total"] == 1
    assert credentials.status("local", "JIRA_READ_API_TOKEN")["configured"] is False


def test_only_one_import_of_a_connection_runs_at_a_time(api):
    api.post("/api/requirements/connections", headers=H, json=CONN)
    import threading
    gate = threading.Event()
    ctx = {"tenant": "local", "actor": "local-user"}
    rapi.JOBS.start(ctx, "jira-main", "full", lambda db, job: (gate.wait(5), {"status": "complete"})[1])
    r = api.post("/api/requirements/connections/jira-main/imports", headers=H,
                 json={"mode": "items", "keys": "SHOP-1"})
    assert r.status_code == 409
    gate.set()


def test_importing_never_runs_tests(api, monkeypatch):
    """Import and analysis only read Atlassian and write the requirements store: no run is started."""
    from backend import server
    started = []
    monkeypatch.setattr(server, "start_run", lambda *a, **k: started.append(a))
    api.post("/api/requirements/connections", headers=H, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    wait_job(api, api.post("/api/requirements/connections/jira-main/imports", headers=H,
                           json={"mode": "full", "filters": {"project": "SHOP"}}).json())
    api.post("/api/requirements/items/jira-main/SHOP-1/analyze", headers=H, json={})
    assert started == [] and not server.jobs or all(
        "requirements" not in json.dumps(j, default=str) for j in server.jobs.values())


def _analysed(api, headers=H):
    api.post("/api/requirements/connections", headers=headers, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=headers, json={"token": TOKEN})
    wait_job(api, api.post("/api/requirements/connections/jira-main/imports", headers=headers,
                           json={"mode": "items", "keys": "SHOP-1"}).json(), headers)
    return api.post("/api/requirements/items/jira-main/SHOP-1/analyze", headers=headers, json={}).json()


def test_the_review_list_shows_ideas_with_their_evidence_and_decisions(api):
    analysed = _analysed(api)
    r = api.get("/api/requirements/reviews").json()
    assert r["can_review"] is True and r["reviewer"] == "local-user"
    assert r["total"] == len(analysed["analysis"]["suggestions"])
    first = r["reviews"][0]
    assert first["key"] == "SHOP-1" and first["criteria"][0]["citation"]["quote"]
    sid = quote(first["suggestion"]["id"], safe="")
    api.post(f"/api/requirements/items/jira-main/SHOP-1/suggestions/{sid}/review", headers=H, json={"answer": "no"})
    done = api.get("/api/requirements/reviews?status=rejected").json()["reviews"]
    assert len(done) == 1 and done[0]["decided_by"] == "local-user" and done[0]["approval_status"] == "rejected"
    assert api.get("/api/requirements/reviews?status=needs_review").json()["total"] == r["total"] - 1
    assert api.get("/api/requirements/reviews?q=no-such-idea").json()["total"] == 0
    assert api.get("/api/requirements/reviews?status=bogus").status_code == 400


def test_accepting_with_corrections_keeps_the_original_and_never_claims_a_quote(api):
    analysed = _analysed(api)
    explicit = next(s for s in analysed["analysis"]["suggestions"] if s["basis"] == "explicit")
    url = f"/api/requirements/items/jira-main/SHOP-1/suggestions/{quote(explicit['id'], safe='')}/review"
    edit = {"title": "Wrong password is refused", "steps": ["Open login", "Type a wrong password"],
            "expected_outcome": "A red banner says the password is wrong"}
    assert api.post(url, headers=H, json={"answer": "no", "edit": edit}).status_code == 400  # (an edit only accepts)
    assert api.get("/api/requirements/reviews").json()["total"] == len(analysed["analysis"]["suggestions"])
    r = api.post(url, headers=H, json={"answer": "yes", "edit": edit})
    s = r.json()["suggestion"]
    assert s["review"] == "accepted" and s["title"] == "Wrong password is refused" and s["edited_by"] == "local-user"
    assert s["basis"] == "inferred"  # (the new outcome is not in the requirement's words)
    assert s["original"]["title"] == explicit["title"] and s["original"]["basis"] == "explicit"
    assert "edited by local-user" in s["note"]


def test_a_viewer_is_told_they_cannot_review(api, monkeypatch):
    _analysed(api)
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    assert api.get("/api/requirements/capabilities", headers=as_("view-1")).json()["can_review"] is False
    assert api.get("/api/requirements/capabilities", headers=as_("op-1")).json()["can_review"] is True
    r = api.get("/api/requirements/reviews", headers=as_("view-1")).json()
    assert r["can_review"] is False and r["reviewer"] is None


def test_the_requirements_page_is_served():
    from fastapi.testclient import TestClient

    from backend import server
    r = TestClient(server.app, base_url="http://127.0.0.1:8000").get("/requirements")
    assert r.status_code == 200 and "Requirements Intelligence" not in r.text.split("<body")[0]
    assert 'src="/static/requirements.js"' in r.text
