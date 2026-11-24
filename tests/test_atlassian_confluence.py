"""Requirements Intelligence, Phase 2: read-only Confluence Cloud pages, linked pages, and story <-> page links.

Everything runs against tests/atlassian_mock.py on 127.0.0.1 (one mock site answers Jira and Confluence paths)."""
import inspect
from datetime import timedelta

import pytest

from backend import audit_store
from backend.atlassian import client as client_mod, confluence, store, sync as sync_mod
from backend.atlassian.client import AtlassianError, Client
from backend.atlassian.models import Connection, SyncStatus
from backend.atlassian.sync import follow_links, link_story, sync_confluence_space, sync_jira
from tests.atlassian_mock import EMAIL, T0, TOKEN, MockAtlassian, page

HOST = "acme-test.atlassian.net"
LATER = T0 + timedelta(days=10)
RULES = ("<h1>Login</h1><p>Intro.</p><h2>Business rules</h2><ul><li><p>Passwords must have 8 characters.</p></li>"
         "<li>Lock the account after 3 wrong tries</li></ul>"
         "<table><tbody><tr><th>Field</th><th>Rule</th></tr><tr><td><p>Email</p></td><td>required</td></tr></tbody></table>")


@pytest.fixture
def mock():
    m = MockAtlassian()
    yield m
    m.close()


@pytest.fixture
def db(tmp_path):
    d = store.connect(tmp_path / "req.sqlite")
    yield d
    d.close()


def conn(product="confluence", tenant="t1", cid=None):
    return Connection(id=cid or ("conf-main" if product == "confluence" else "jira-main"), tenant_id=tenant,
                      product=product, site_url=f"https://{HOST}", email=EMAIL, token_ref="JIRA_READ_API_TOKEN")


def client(mock, connection=None, **kw):
    return Client(connection or conn(), base_url=mock.url, secret=lambda n: TOKEN, sleep=lambda s: None, **kw)


def space_sync(db, mock, tmp_path, **kw):
    c = kw.pop("client", None) or client(mock)
    return sync_confluence_space(db, conn(), c, tenant_id=kw.pop("tenant_id", "t1"), space_key="ENG",
                                 page_size=kw.pop("page_size", 10), audit_db=tmp_path / "audit.sqlite",
                                 now=kw.pop("now", LATER), actor="mani", **kw)


def walk(db, mock, tmp_path, ids, **kw):
    return follow_links(db, conn(), kw.pop("client", None) or client(mock), tenant_id=kw.pop("tenant_id", "t1"),
                        page_ids=ids, audit_db=tmp_path / "audit.sqlite", now=LATER, **kw)


def add_pages(mock, n, start=1):
    for i in range(start, start + n):
        mock.add_page(str(1000 + i), f"Spec {i}", f"<h2>Rules</h2><p>Spec {i} must work.</p>",
                      when=T0 + timedelta(minutes=10 * i))


# ---------------------------------------------------------------- reading

def test_spaces_are_found_by_key_and_page_by_page(mock):
    mock.spaces = [{"id": str(100 + i), "key": f"S{i}", "name": f"Space {i}", "type": "global", "status": "current"}
                   for i in range(60)]
    assert len(confluence.spaces(client(mock))) == 60
    assert confluence.spaces(client(mock), ["S7"])[0]["id"] == "107"
    with pytest.raises(ValueError):
        confluence.spaces(client(mock), ["bad key!"])


def test_a_page_becomes_sections_with_their_heading_path():
    found = confluence.extract(RULES, HOST)
    intro, rules = found["sections"]
    assert intro["path"] == ["Login"] and not intro["requirement_like"]
    assert rules["path"] == ["Login", "Business rules"] and rules["requirement_like"]
    assert [b["text"] for b in rules["blocks"]] == ["Passwords must have 8 characters.",
                                                     "Lock the account after 3 wrong tries", "Field | Rule",
                                                     "Email | required"]
    assert [b["type"] for b in rules["blocks"]] == ["list_item", "list_item", "table_row", "table_row"]


def test_tasks_code_nested_lists_and_macros_are_read_as_written():
    body = ("<h2>Scenarios</h2><ul><li>Checkout<ul><li>with a coupon</li></ul></li></ul>"
            "<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>incomplete</ac:task-status>"
            "<ac:task-body>Confirm the copy</ac:task-body></ac:task></ac:task-list>"
            '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[Given a cart\nWhen I pay\nThen it is paid]]>'
            "</ac:plain-text-body></ac:structured-macro>")
    blocks = confluence.extract(body, HOST)["sections"][0]["blocks"]
    assert [(b["type"], b["text"]) for b in blocks] == [
        ("list_item", "Checkout"), ("list_item", "with a coupon"), ("task", "Confirm the copy"),
        ("code", "Given a cart\nWhen I pay\nThen it is paid")]


def test_links_to_pages_and_stories_are_found_and_other_sites_only_counted():
    body = ('<p>See <ac:link><ri:page ri:space-key="ENG" ri:content-title="Password policy" /></ac:link>, '
            f'<a href="https://{HOST}/wiki/spaces/ENG/pages/555/Security">security</a>, '
            f'<a href="https://{HOST}/browse/SHOP-12">the story</a>, <a href="https://evil.example/wiki/spaces/X/pages/9">x</a>.'
            '</p><ac:structured-macro ac:name="jira"><ac:parameter ac:name="key">SHOP-40</ac:parameter>'
            "</ac:structured-macro><p>Text is UTF-8.</p>")
    found = confluence.extract(body, HOST)
    assert found["links"]["page_ids"] == ["555"] and found["links"]["page_titles"] == [["ENG", "Password policy"]]
    assert {"SHOP-12", "SHOP-40"} <= set(found["links"]["issues"]) and found["links"]["external"] == 1
    assert "See Password policy, security" in found["sections"][0]["blocks"][0]["text"]


def test_a_malformed_page_is_read_as_far_as_it_goes():
    found = confluence.extract("<h2>Rules<p>Must log in<ul><li>first<li>second", HOST)
    assert [(s["heading"], [b["text"] for b in s["blocks"]]) for s in found["sections"]] == [
        ("Rules", ["Must log in", "first", "second"])]
    with pytest.raises(ValueError):
        confluence.extract(None, HOST)


def test_a_very_large_page_is_capped_but_its_hash_covers_everything():
    body = "".join(f"<h2>Part {i}</h2><p>Rule {i} must hold.</p>" for i in range(1000))
    found = confluence.extract(body, HOST)
    assert found["truncated"] and len(found["sections"]) == confluence.MAX_SECTIONS
    assert "Rule 999 must hold." in found["text"]
    huge = confluence.extract("<p>" + "x" * 10000 + "</p>", HOST)
    assert huge["truncated"] and len(huge["sections"][0]["blocks"][0]["text"]) == confluence.MAX_BLOCK_CHARS


def test_a_page_keeps_confluences_own_version_and_link():
    p = page("1001", "Login spec", RULES, version=7, when=T0)
    item = confluence.normalize(p, conn(), space_key="ENG", retrieved_at=LATER)
    s = item["source"]
    assert s.version == 7 and s.updated == T0 and s.kind.value == "confluence_page"
    assert s.url == f"https://{HOST}/wiki/spaces/ENG/pages/1001/Login+spec"
    assert item["content"]["confluence_version"] == 7
    for broken in ({**p, "status": "trashed"}, {**p, "version": {}}, {**p, "title": ""}, {**p, "id": "abc"}):
        with pytest.raises(ValueError):
            confluence.normalize(broken, conn())


# ---------------------------------------------------------------- space sync

def test_the_first_space_sync_reads_every_page(mock, db, tmp_path):
    add_pages(mock, 30)
    out = space_sync(db, mock, tmp_path)
    assert out["status"] == "complete" and out["new"] == 30 and out["pages"] == 3
    stored = store.list_sources(db, "t1", "conf-main")
    assert len(stored) == 30 and stored[0]["source"].version == 1
    assert {r["method"] for r in mock.requests} == {"GET"}
    assert audit_store.list_audits(tenant_id="t1", db_path=tmp_path / "audit.sqlite")[0]["action"] == \
        "requirements.sync.confluence"


def test_a_later_sync_reads_only_changed_pages_and_keeps_both_versions(mock, db, tmp_path):
    add_pages(mock, 30)
    space_sync(db, mock, tmp_path)
    mock.edit_page("1005", "<h2>Rules</h2><p>Spec 5 must work on phones too.</p>", LATER + timedelta(days=1))
    mock.requests.clear()
    out = space_sync(db, mock, tmp_path, now=LATER + timedelta(days=2))
    assert out["changed"] == 1 and out["new"] == 0 and out["pages"] == 1  # (stopped at the first older page)
    key = "conf-main:confluence_page:1005"
    assert [v["source"].version for v in store.history(db, "t1", key)] == [1, 2]
    assert store.history(db, "t1", key)[0]["content"]["sections"][0]["blocks"][0]["text"] == "Spec 5 must work."


def test_a_space_sync_resumes_after_a_page_limit_or_a_failure(mock, db, tmp_path):
    add_pages(mock, 30)
    out = space_sync(db, mock, tmp_path, max_pages=1)
    assert out["status"] == "running" and out["new"] == 10
    mock.fail("/wiki/api/v2/spaces/100/pages", 503, times=5)
    out = space_sync(db, mock, tmp_path, client=client(mock, max_retries=1))
    assert out["status"] == "failed" and out["resumed"]
    cur = store.load_cursor(db, "t1", "conf-main", "space:ENG")
    assert cur.status == SyncStatus.failed and cur.next_page_token
    mock.faults.clear()
    out = space_sync(db, mock, tmp_path)
    assert out["resumed"] and out["status"] == "complete" and out["new"] == 20
    assert len(store.list_sources(db, "t1")) == 30


def test_rate_limits_are_waited_out_and_an_expired_token_stops(mock, db, tmp_path):
    add_pages(mock, 3)
    mock.fail("/wiki/api/v2/spaces/100/pages", 429, times=2, headers={"Retry-After": "1"})
    assert space_sync(db, mock, tmp_path)["status"] == "complete"
    bad = Client(conn(), base_url=mock.url, secret=lambda n: "old-token-123", sleep=lambda s: None)
    out = space_sync(db, mock, tmp_path, client=bad, full=True)
    assert out["status"] == "failed" and out["error"].startswith("auth_expired") and "old-token-123" not in out["error"]


def test_an_unknown_space_and_a_broken_page_are_reported_not_hidden(mock, db, tmp_path):
    out = sync_confluence_space(db, conn(), client(mock), tenant_id="t1", space_key="NOPE",
                                audit_db=tmp_path / "audit.sqlite")
    assert out["status"] == "failed" and "NOPE" in out["error"]
    add_pages(mock, 4)
    mock.pages["1002"]["title"] = ""
    out = space_sync(db, mock, tmp_path)
    assert out["status"] == "partial" and out["new"] == 3 and out["failed_items"][0].startswith("1002:")


def test_deleted_pages_are_kept_as_missing(mock, db, tmp_path):
    add_pages(mock, 5)
    space_sync(db, mock, tmp_path)
    mock.pages["1003"]["status"] = "deleted"
    out = space_sync(db, mock, tmp_path, full=True)
    assert out["missing"] == ["conf-main:confluence_page:1003"]
    assert len(store.list_sources(db, "t1")) == 4 and store.history(db, "t1", "conf-main:confluence_page:1003")


# ---------------------------------------------------------------- linked pages

def chain(mock, ids, loop=False):
    for i, pid in enumerate(ids):
        nxt = ids[(i + 1) % len(ids)] if (loop or i + 1 < len(ids)) else None
        link = f'<a href="https://{HOST}/wiki/spaces/ENG/pages/{nxt}/x">next</a>' if nxt else ""
        mock.add_page(pid, f"Page {pid}", f"<h2>Rules</h2><p>Page {pid} must be read. {link}</p>")


def test_circular_links_read_each_page_once(mock, db, tmp_path):
    chain(mock, ["1", "2", "3"], loop=True)
    out = walk(db, mock, tmp_path, ["1"], depth=10)
    assert out["pages"] == [f"conf-main:confluence_page:{i}" for i in ("1", "2", "3")] and not out["error"]
    assert sum(r["path"].startswith("/wiki/api/v2/pages/") for r in mock.requests) == 3
    assert store.links_from(db, "t1", "conf-main:confluence_page:3") == [
        {"to_key": "conf-main:confluence_page:1", "relation": "links_to", "found_via": "page body"}]


def test_depth_and_page_limits_are_respected(mock, db, tmp_path):
    chain(mock, ["1", "2", "3", "4"])
    assert len(walk(db, mock, tmp_path, ["1"], depth=1)["pages"]) == 2
    assert len(walk(db, mock, tmp_path, ["1"], depth=0)["pages"]) == 1
    out = walk(db, mock, tmp_path, ["1"], depth=10, max_pages=2)
    assert out["limit_reached"] and len(out["pages"]) == 2
    with pytest.raises(ValueError):
        walk(db, mock, tmp_path, ["1"], depth=-1)


def test_inaccessible_and_deleted_pages_do_not_stop_the_others(mock, db, tmp_path):
    mock.add_page("1", "Hub", f'<p><a href="https://{HOST}/wiki/spaces/ENG/pages/2/x">a</a> '
                              f'<a href="https://{HOST}/wiki/spaces/ENG/pages/3/x">b</a> '
                              f'<a href="https://{HOST}/wiki/spaces/ENG/pages/4/x">c</a></p>')
    mock.add_page("2", "Secret", "<p>hidden</p>")
    mock.add_page("4", "Open", "<p>Must be readable.</p>")
    walk(db, mock, tmp_path, ["2"], depth=0)  # (stored once, before it became secret)
    mock.forbidden.add("2")
    out = walk(db, mock, tmp_path, ["1"], depth=1)
    assert sorted(out["inaccessible"], key=lambda x: x["page_id"]) == [{"page_id": "2", "why": "forbidden"},
                                                                       {"page_id": "3", "why": "not_found"}]
    assert out["pages"] == ["conf-main:confluence_page:1", "conf-main:confluence_page:4"]
    assert not store.get_source(db, "t1", "conf-main:confluence_page:2")["present"]


def test_a_page_too_large_to_read_is_a_failure_not_a_deletion(mock, db, tmp_path, monkeypatch):
    mock.add_page("1", "Big", "<p>" + "x" * 5000 + "</p>")
    monkeypatch.setattr(client_mod, "MAX_BYTES", 1000)
    out = walk(db, mock, tmp_path, ["1"], depth=0)
    assert out["failed_items"] == ["1: too_large"] and not out["inaccessible"]


def test_links_by_title_are_resolved_in_their_space(mock, db, tmp_path):
    mock.add_page("1", "Story spec", '<p>See <ac:link><ri:page ri:content-title="Password policy" /></ac:link> and '
                                     '<ac:link><ri:page ri:content-title="Gone page" /></ac:link></p>')
    mock.add_page("2", "Password policy", "<p>Passwords must have 8 characters.</p>")
    out = walk(db, mock, tmp_path, ["1"], depth=1)
    assert "conf-main:confluence_page:2" in out["pages"]
    assert {"page_id": "", "title": "Gone page", "why": "not_found"} in out["inaccessible"]


def test_a_site_wide_failure_stops_the_walk_with_its_reason(mock, db, tmp_path):
    chain(mock, ["1", "2"])
    mock.fail("/wiki/api/v2/pages/2", 503, times=10)
    out = walk(db, mock, tmp_path, ["1"], depth=1, client=client(mock, max_retries=1))
    assert out["pages"] == ["conf-main:confluence_page:1"] and out["error"].startswith("server")


# ---------------------------------------------------------------- Jira story <-> Confluence pages

def test_a_story_is_linked_to_the_pages_that_specify_it(mock, db, tmp_path):
    mock.add_stories(3)
    mock.issues["SHOP-2"]["fields"]["description"] = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": f"Rules: https://{HOST}/wiki/spaces/ENG/pages/2/Rules and https://evil.example/wiki/spaces/X/pages/9"}]}]}
    mock.remote_links["SHOP-2"] = [{"globalId": "appId=abc&pageId=1", "application": {"type": "com.atlassian.confluence"},
                                    "object": {"url": f"https://{HOST}/wiki/pages/viewpage.action?pageId=1",
                                               "title": "Login spec"}}]
    mock.add_page("1", "Login spec", f'<h2>Acceptance</h2><p>Must log in. <a href="https://{HOST}/wiki/spaces/ENG/pages/5/x">'
                                     "policy</a></p>")
    mock.add_page("2", "Rules", "<p>Shall lock after 3 tries.</p>")
    mock.add_page("3", "Release notes", '<p><ac:structured-macro ac:name="jira"><ac:parameter ac:name="key">SHOP-2'
                                        "</ac:parameter></ac:structured-macro> shipped. Encoding UTF-8.</p>")
    mock.add_page("5", "Password policy", "<p>8 characters.</p>")
    jira_c = conn("jira")
    sync_jira(db, jira_c, client(mock, jira_c), tenant_id="t1", project="SHOP", audit_db=tmp_path / "audit.sqlite",
              now=LATER)
    space_sync(db, mock, tmp_path)  # (finds page 3 mentioning SHOP-2)
    out = link_story(db, jira_c, client(mock, jira_c), conn(), client(mock), tenant_id="t1", issue_key="SHOP-2",
                     depth=1, audit_db=tmp_path / "audit.sqlite", now=LATER)
    story = "jira-main:jira_issue:SHOP-2"
    assert set(out["linked"]) >= {"conf-main:confluence_page:1", "conf-main:confluence_page:2",
                                  "conf-main:confluence_page:5"}
    got = {(link["to_key"], link["found_via"]) for link in store.links_from(db, "t1", story)}
    assert ("conf-main:confluence_page:1", "jira remote link") in got
    assert ("conf-main:confluence_page:2", "jira description") in got
    assert ("conf-main:confluence_page:3", "page mentions the story") in got
    assert store.links_from(db, "t1", "conf-main:confluence_page:1")[0]["to_key"] == "conf-main:confluence_page:5"
    mentions = [link["to_key"] for link in store.links_from(db, "t1", "conf-main:confluence_page:3")]
    assert mentions == [story]  # ('UTF-8' is not a story: no link)
    assert {r["method"] for r in mock.requests} <= {"GET", "POST"}
    assert all(r["path"] == "/rest/api/3/search/jql" for r in mock.requests if r["method"] == "POST")


def test_linking_needs_a_synced_story_and_survives_unreadable_remote_links(mock, db, tmp_path):
    jira_c = conn("jira")
    with pytest.raises(LookupError):
        link_story(db, jira_c, client(mock, jira_c), conn(), client(mock), tenant_id="t1", issue_key="SHOP-1",
                   audit_db=tmp_path / "audit.sqlite")
    mock.add_stories(1)
    sync_jira(db, jira_c, client(mock, jira_c), tenant_id="t1", project="SHOP", audit_db=tmp_path / "audit.sqlite",
              now=LATER)
    mock.fail("/rest/api/3/issue/SHOP-1/remotelink", 403)
    out = link_story(db, jira_c, client(mock, jira_c), conn(), client(mock), tenant_id="t1", issue_key="SHOP-1",
                     audit_db=tmp_path / "audit.sqlite")
    assert out["notes"] == ["remote links not readable (forbidden)"] and out["linked"] == []


# ---------------------------------------------------------------- tenants, secrets, no AI

def test_tenants_never_see_each_others_pages_or_links(mock, db, tmp_path):
    chain(mock, ["1", "2"])
    walk(db, mock, tmp_path, ["1"], depth=1)
    assert store.list_sources(db, "t2") == [] and store.links_from(db, "t2", "conf-main:confluence_page:1") == []
    with pytest.raises(PermissionError):
        walk(db, mock, tmp_path, ["1"], tenant_id="t2")
    with pytest.raises(PermissionError):
        space_sync(db, mock, tmp_path, tenant_id="t2")
    t2 = conn(tenant="t2")
    walk_t2 = follow_links(db, t2, client(mock, t2), tenant_id="t2", page_ids=["1"], depth=0,
                           audit_db=tmp_path / "audit.sqlite")
    assert walk_t2["pages"] == ["conf-main:confluence_page:1"]
    assert len(store.list_sources(db, "t1")) == 2 and len(store.list_sources(db, "t2")) == 1
    refused = audit_store.list_audits(tenant_id="t2", db_path=tmp_path / "audit.sqlite")
    assert any(not a["allowed"] for a in refused)


def test_no_token_in_any_stored_file_and_no_ai_in_this_phase(mock, db, tmp_path):
    add_pages(mock, 3)
    space_sync(db, mock, tmp_path)
    db.commit()
    for f in tmp_path.iterdir():
        assert TOKEN.encode() not in f.read_bytes()
    for module in (confluence, sync_mod, store):
        source = inspect.getsource(module)
        assert "backend.llm" not in source and "from ..llm" not in source and "chat(" not in source


def test_only_the_confluence_api_paths_are_called(mock):
    c = client(mock)
    with pytest.raises(ValueError):
        confluence.get_page(c, "1/../../admin")
    with pytest.raises(ValueError):
        confluence.space_pages(c, "abc")
    with pytest.raises(AtlassianError):
        c.post_read("/wiki/api/v2/pages", {"title": "x"})
    assert not mock.requests
