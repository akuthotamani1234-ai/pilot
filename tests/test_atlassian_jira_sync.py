"""Requirements Intelligence, Phase 1: the read-only Jira Cloud connector and its incremental, resumable sync.

Everything runs against tests/atlassian_mock.py on 127.0.0.1 (no real Atlassian site, no real data)."""
from datetime import UTC, datetime, timedelta

import pytest

from backend import audit_store
from backend.atlassian import client as client_mod, jira, store
from backend.atlassian.client import AtlassianError, Client, retry_after_seconds
from backend.atlassian.models import Connection, SyncStatus
from backend.atlassian.sync import sync_jira
from tests.atlassian_mock import EMAIL, T0, TOKEN, MockJira, adf, story

LATER = T0 + timedelta(days=10)


@pytest.fixture
def mock():
    m = MockJira()
    yield m
    m.close()


def conn(tenant="t1", **kw):
    return Connection(**{"id": "jira-main", "tenant_id": tenant, "product": "jira",
                         "site_url": "https://acme-test.atlassian.net", "email": EMAIL,
                         "token_ref": "JIRA_READ_API_TOKEN", **kw})


def client(mock, connection=None, **kw):
    sleeps = []
    c = Client(connection or conn(), base_url=mock.url, secret=lambda name: TOKEN if name == "JIRA_READ_API_TOKEN" else "",
               sleep=sleeps.append, **kw)
    c.sleeps = sleeps
    return c


@pytest.fixture
def db(tmp_path):
    d = store.connect(tmp_path / "req.sqlite")
    yield d
    d.close()


# ---------------------------------------------------------------- client: reads only, safely

def test_429_waits_for_retry_after_then_succeeds(mock):
    mock.fail("/rest/api/3/field", 429, times=2, headers={"Retry-After": "3"})
    c = client(mock)
    assert jira.acceptance_field(c) == "customfield_10045"
    assert c.sleeps == [3.0, 3.0] and c.calls == 3


def test_server_errors_back_off_and_then_give_up(mock):
    mock.fail("/rest/api/3/field", 503, times=10)
    c = client(mock, max_retries=3, backoff=0.5)
    with pytest.raises(AtlassianError) as e:
        jira.acceptance_field(c)
    assert e.value.kind == "server" and c.calls == 4 and c.sleeps == [0.5, 1.0, 2.0]


def test_retry_after_is_capped_and_may_be_a_date():
    assert retry_after_seconds("120") == 120
    assert retry_after_seconds("Wed, 21 Oct 2015 07:28:10 GMT", now=1445412480.0) == 10
    assert retry_after_seconds("soon") is None


def test_wait_never_exceeds_the_cap(mock):
    mock.fail("/rest/api/3/field", 429, headers={"Retry-After": "3600"})
    c = client(mock, max_wait=30)
    jira.acceptance_field(c)
    assert c.sleeps == [30]


def test_an_expired_token_stops_at_once_without_showing_it(mock):
    c = Client(conn(), base_url=mock.url, secret=lambda n: "wrong-token-value-999", sleep=lambda s: None)
    with pytest.raises(AtlassianError) as e:
        jira.projects(c)
    assert e.value.kind == "auth_expired" and c.calls == 1
    assert "JIRA_READ_API_TOKEN" in str(e.value) and "wrong-token-value-999" not in str(e.value)


def test_a_missing_secret_sends_nothing(mock):
    c = Client(conn(), base_url=mock.url, secret=lambda n: "")
    with pytest.raises(AtlassianError) as e:
        jira.projects(c)
    assert e.value.kind == "auth_missing" and not mock.requests


def test_an_error_text_never_carries_the_token(mock):
    mock.fail("/rest/api/3/project/search", 400, body=f"bad value {TOKEN} ATATT3xFfGF0abcdefghijklmnopq")
    with pytest.raises(AtlassianError) as e:
        jira.projects(client(mock))
    assert TOKEN not in str(e.value) and "ATATT" not in str(e.value)


def test_redirects_are_not_followed(mock):
    mock.fail("/rest/api/3/field", 302, headers={"Location": "https://evil.example/steal"})
    with pytest.raises(AtlassianError) as e:
        jira.acceptance_field(client(mock))
    assert e.value.kind == "redirect" and len(mock.requests) == 1


def test_only_reads_are_possible(mock):
    c = client(mock)
    for path in ("/rest/api/3/issue", "/rest/api/3/issue/SHOP-1/comment"):
        with pytest.raises(AtlassianError) as e:
            c.post_read(path, {"fields": {}})
        assert e.value.kind == "refused"
    with pytest.raises(AtlassianError):
        c.get("https://evil.example/x")
    with pytest.raises(AtlassianError):
        c.get("/rest/api/3/../../x")
    assert not mock.requests
    assert not any(hasattr(c, name) for name in ("post", "put", "delete", "patch"))


def test_a_test_server_must_be_on_this_computer():
    with pytest.raises(AtlassianError):
        Client(conn(), base_url="http://10.0.0.5:8080")
    assert Client(conn()).base_url == "https://acme-test.atlassian.net"


def test_an_oversized_answer_is_refused(mock, monkeypatch):
    monkeypatch.setattr(client_mod, "MAX_BYTES", 100)
    mock.add_stories(5)
    with pytest.raises(AtlassianError) as e:
        jira.search(client(mock), "project = SHOP", ["summary"])
    assert e.value.kind == "too_large"


# ---------------------------------------------------------------- jira reads and normalization

def test_jql_is_built_safely():
    assert jira.build_jql("SHOP") == 'project = SHOP AND issuetype in ("Story") ORDER BY updated ASC, key ASC'
    q = jira.build_jql("SHOP", ("Story", 'Bug "x"'), extra='labels = "checkout"',
                       since=datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
    assert '"Bug \\"x\\""' in q and '(labels = "checkout")' in q and 'updated >= "2026/11/19 21:59"' in q
    for bad in ("shop", "SHOP OR 1=1", ""):
        with pytest.raises(ValueError):
            jira.build_jql(bad)
    with pytest.raises(ValueError):
        jira.build_jql("SHOP", extra="labels = x ORDER BY key")


def test_projects_are_read_page_by_page(mock):
    mock.projects = [{"id": str(i), "key": f"P{i}", "name": f"Project {i}"} for i in range(1, 121)]
    found = jira.projects(client(mock))
    assert len(found) == 120 and found[0] == {"id": "1", "key": "P1", "name": "Project 1"}
    assert sum(r["path"] == "/rest/api/3/project/search" for r in mock.requests) == 3


def test_the_acceptance_criteria_field_is_found_by_name(mock):
    assert jira.acceptance_field(client(mock)) == "customfield_10045"
    mock.fields = [{"id": "summary", "name": "Summary", "custom": False}]
    assert jira.acceptance_field(client(mock)) == ""


def test_adf_becomes_readable_text():
    doc = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Rules"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "Line one"}, {"type": "hardBreak"},
                                          {"type": "text", "text": "line two"}]},
        {"type": "orderedList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "First"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Second"}]}]}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Dot"}]}]}]},
        {"type": "table", "content": [{"type": "tableRow", "content": [
            {"type": "tableHeader", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "A"}]}]},
            {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "B"}]}]}]}]}]}
    assert jira.adf_to_text(doc) == "## Rules\nLine one\nline two\n1. First\n2. Second\n- Dot\nA | B"
    assert jira.adf_to_text("plain wiki text") == "plain wiki text" and jira.adf_to_text(None) == ""


def test_a_story_is_normalized_with_its_source_and_a_stable_hash():
    issue = story("SHOP-12", "Login", T0, "As a shopper I log in.", "A wrong password shows an error.",
                  labels=["auth", "web"], issuelinks=[{"type": {"outward": "blocks", "inward": "is blocked by"},
                                                       "outwardIssue": {"key": "SHOP-13"}}])
    item = jira.normalize(issue, conn(), ac_field="customfield_10045", retrieved_at=LATER)
    s = item["source"]
    assert s.source_id == "SHOP-12" and s.url == "https://acme-test.atlassian.net/browse/SHOP-12"
    assert s.updated == T0 and s.key == "jira-main:jira_issue:SHOP-12"
    assert item["story"]["acceptance_criteria"] == "A wrong password shows an error."
    assert item["story"]["links"] == [{"key": "SHOP-13", "type": "blocks"}]
    again = jira.normalize(issue, conn(), ac_field="customfield_10045", retrieved_at=LATER + timedelta(days=1))
    assert again["source"].content_hash == s.content_hash
    issue["fields"]["description"] = adf("As a shopper I log in with email.")
    assert jira.normalize(issue, conn(), ac_field="customfield_10045")["source"].content_hash != s.content_hash
    with pytest.raises(ValueError):
        jira.normalize(story("SHOP-14", "", T0), conn())


# ---------------------------------------------------------------- sync

def sync(db, mock, tmp_path, **kw):
    c = kw.pop("client", None) or client(mock)
    return sync_jira(db, kw.pop("connection", conn()), c, tenant_id=kw.pop("tenant_id", "t1"), project="SHOP",
                     page_size=kw.pop("page_size", 50), audit_db=tmp_path / "audit.sqlite", now=kw.pop("now", LATER),
                     actor="mani", **kw)


def test_the_first_sync_reads_every_story_page_by_page(mock, db, tmp_path):
    mock.add_stories(120)
    out = sync(db, mock, tmp_path)
    assert out["status"] == "complete" and out["new"] == 120 and out["pages"] == 3 and not out["failed_items"]
    assert len(store.list_sources(db, "t1")) == 120
    cur = store.load_cursor(db, "t1", "jira-main", out["scope"])
    assert cur.status == SyncStatus.complete and cur.high_water == LATER and not cur.next_page_token
    assert {(r["method"], r["path"]) for r in mock.requests} == {("GET", "/rest/api/3/field"),
                                                                ("POST", "/rest/api/3/search/jql")}
    audit = audit_store.list_audits(tenant_id="t1", db_path=tmp_path / "audit.sqlite")
    assert audit and audit[0]["action"] == "requirements.sync.jira" and audit[0]["actor"] == "mani"


def test_a_later_sync_reads_only_changes_and_keeps_every_version(mock, db, tmp_path):
    mock.add_stories(30)
    sync(db, mock, tmp_path)
    mock.requests.clear()
    mock.touch("SHOP-7", LATER + timedelta(days=1), summary="Story 7, now with coupons")
    mock.touch("SHOP-9", LATER + timedelta(days=1))  # (re-saved without a change)
    out = sync(db, mock, tmp_path, now=LATER + timedelta(days=2))
    assert out["changed"] == 1 and out["unchanged"] == 1 and out["new"] == 0
    search = next(r for r in mock.requests if r["path"].endswith("/search/jql"))
    assert 'updated >= "2026/11/10 18:59"' in search["body"]["jql"]  # (last sync time minus the 14 h overlap)
    key = "jira-main:jira_issue:SHOP-7"
    versions = store.history(db, "t1", key)
    assert [v["source"].version for v in versions] == [1, 2]
    assert versions[0]["content"]["summary"] == "Story 7" and store.get_source(db, "t1", key)["source"].version == 2
    assert [v["source"].version for v in store.history(db, "t1", "jira-main:jira_issue:SHOP-9")] == [1]


def test_a_failed_sync_resumes_from_its_last_stored_page(mock, db, tmp_path):
    mock.add_stories(120)
    c = client(mock, max_retries=1)
    first = {"done": False}
    real = c.post_read

    def flaky(path, body):
        if body.get("nextPageToken") and not first["done"]:
            first["done"] = True
            mock.fail("/rest/api/3/search/jql", 503, times=5)
        return real(path, body)
    c.post_read = flaky
    out = sync(db, mock, tmp_path, client=c)
    assert out["status"] == "failed" and out["new"] == 50 and "server" in out["error"]
    cur = store.load_cursor(db, "t1", "jira-main", out["scope"])
    assert cur.status == SyncStatus.failed and cur.next_page_token and cur.high_water is None
    mock.faults.clear()
    mock.requests.clear()
    again = sync(db, mock, tmp_path)
    assert again["resumed"] and again["status"] == "complete" and again["new"] == 70 and again["pages"] == 2
    assert len(store.list_sources(db, "t1")) == 120


def test_a_page_limit_leaves_a_resumable_sync(mock, db, tmp_path):
    mock.add_stories(120)
    out = sync(db, mock, tmp_path, max_pages=1)
    assert out["status"] == "running" and out["new"] == 50
    out = sync(db, mock, tmp_path)
    assert out["resumed"] and out["new"] == 70 and out["status"] == "complete"


def test_an_expired_page_token_reads_the_same_query_again(mock, db, tmp_path):
    mock.add_stories(120)
    sync(db, mock, tmp_path, max_pages=1)
    mock.expire_tokens()
    out = sync(db, mock, tmp_path)
    assert out["status"] == "complete" and out["new"] == 70 and out["unchanged"] == 50
    assert len(store.list_sources(db, "t1")) == 120


def test_one_unreadable_story_does_not_stop_the_others(mock, db, tmp_path):
    mock.add_stories(10)
    mock.issues["SHOP-4"]["fields"]["summary"] = ""
    out = sync(db, mock, tmp_path)
    assert out["status"] == "partial" and out["new"] == 9 and out["failed_items"][0].startswith("SHOP-4:")
    cur = store.load_cursor(db, "t1", "jira-main", out["scope"])
    assert cur.high_water is None  # (the next sync reads the whole window again and retries SHOP-4)
    mock.issues["SHOP-4"]["fields"]["summary"] = "Story 4"
    out = sync(db, mock, tmp_path)
    assert out["status"] == "complete" and out["new"] == 1 and out["unchanged"] == 9


def test_stories_no_longer_visible_are_kept_as_missing(mock, db, tmp_path):
    mock.add_stories(5)
    sync(db, mock, tmp_path)
    del mock.issues["SHOP-3"]
    out = sync(db, mock, tmp_path, full=True)
    assert out["missing"] == ["jira-main:jira_issue:SHOP-3"]
    assert len(store.list_sources(db, "t1")) == 4 and len(store.list_sources(db, "t1", include_missing=True)) == 5
    assert store.history(db, "t1", "jira-main:jira_issue:SHOP-3")  # (its history stays for traceability)
    mock.add_stories(1, start=3)
    out = sync(db, mock, tmp_path, full=True)
    assert out["reappeared"] == 1


def test_a_401_during_sync_fails_cleanly_and_is_audited(mock, db, tmp_path):
    mock.add_stories(3)
    c = Client(conn(), base_url=mock.url, secret=lambda n: "expired-token-0000", sleep=lambda s: None)
    out = sync(db, mock, tmp_path, client=c)
    assert out["status"] == "failed" and out["error"].startswith("auth_expired")
    assert "expired-token-0000" not in out["error"]


# ---------------------------------------------------------------- tenants and secrets

def test_one_tenant_cannot_use_or_read_another_tenants_data(mock, db, tmp_path):
    mock.add_stories(3)
    sync(db, mock, tmp_path)
    assert store.list_sources(db, "t2") == [] and store.get_source(db, "t2", "jira-main:jira_issue:SHOP-1") is None
    with pytest.raises(PermissionError):
        sync(db, mock, tmp_path, tenant_id="t2")  # (t1's connection)
    refused = audit_store.list_audits(tenant_id="t2", db_path=tmp_path / "audit.sqlite")
    assert refused and refused[0]["allowed"] in (0, False)
    with pytest.raises(ValueError):
        store.list_sources(db, "")


def test_connections_are_stored_per_tenant_without_the_token(mock, db, tmp_path):
    store.save_connection(db, conn())
    store.save_connection(db, conn(tenant="t2", email="other@acme.test"))
    assert store.get_connection(db, "t1", "jira-main").email == EMAIL
    assert store.get_connection(db, "t2", "jira-main").email == "other@acme.test"
    assert [c.tenant_id for c in store.list_connections(db, "t1")] == ["t1"]
    mock.add_stories(3)
    sync(db, mock, tmp_path)
    db.commit()
    for f in tmp_path.iterdir():
        assert TOKEN.encode() not in f.read_bytes()
