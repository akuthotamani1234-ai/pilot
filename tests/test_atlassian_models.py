"""Requirements Intelligence, Phase 0: the data contracts refuse what the design forbids.

No network: these are schema rules only (docs/REQUIREMENTS_INTELLIGENCE.md)."""
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.atlassian import models as m

NOW = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
STORY = ("As a shopper I want to log in.\nAcceptance criteria:\n"
         "1. Given a registered user, when they enter a valid password, then the dashboard is shown.\n"
         "2. A wrong password shows 'Invalid credentials'.")


def conn(**kw):
    base = {"id": "jira-main", "tenant_id": "t1", "product": "jira", "site_url": "https://acme-test.atlassian.net",
                "email": "qa@acme.test", "token_ref": "JIRA_API_TOKEN"}
    return m.Connection(**{**base, **kw})


def src(**kw):
    base = {"tenant_id": "t1", "connection_id": "jira-main", "kind": "jira_issue", "source_id": "SHOP-12", "version": 1,
                "updated": NOW, "url": "https://acme-test.atlassian.net/browse/SHOP-12", "title": "Login",
                "content_hash": m.content_hash(STORY), "retrieved_at": NOW}
    return m.SourceRef(**{**base, **kw})


def cite(quote=STORY, **kw):
    return m.Citation(source=kw.pop("source", None) or src(), locator=kw.pop("locator", "description"), quote=quote)


def ac(**kw):
    base = {"id": "SHOP-12#AC-2", "requirement_id": "SHOP-12", "text": "A wrong password shows 'Invalid credentials'.",
                "expected_outcome": "shows 'Invalid credentials'", "citations": [cite()], "extraction": "rules"}
    return m.AcceptanceCriterion(**{**base, **kw})


# ---------------------------------------------------------------- connection

def test_only_atlassian_cloud_sites_over_https():
    assert conn().site_url == "https://acme-test.atlassian.net"
    assert conn(site_url="https://ACME-test.atlassian.net/wiki/").host == "acme-test.atlassian.net"
    for bad in ("http://acme.atlassian.net", "https://jira.acme.com", "https://acme.atlassian.net.evil.com",
                "https://user@acme.atlassian.net", "https://acme.atlassian.net:8443", "https://acme.atlassian.net/x?y=1"):
        with pytest.raises(ValidationError):
            conn(site_url=bad)


def test_a_connection_holds_the_secret_name_never_the_token():
    for bad in ("ATATT3xFfGF0abcdefghijklmnop", "jira_api_token", "a" * 45):
        with pytest.raises(ValidationError):
            conn(token_ref=bad)
    assert conn().model_dump()["token_ref"] == "JIRA_API_TOKEN"
    assert not {"token", "api_token", "password"} & set(conn().model_dump())


def test_connections_are_read_only_by_default():
    c = conn()
    assert c.read_only and not c.allow_writes
    with pytest.raises(ValidationError):
        conn(allow_writes=True)  # (still read_only)
    assert conn(read_only=False, allow_writes=True).allow_writes


def test_unknown_fields_are_refused():
    with pytest.raises(ValidationError):
        conn(api_token="x")


# ---------------------------------------------------------------- sources

def test_a_source_has_a_real_id_version_link_and_hash():
    s = src()
    assert s.key == "jira-main:jira_issue:SHOP-12"
    with pytest.raises(ValidationError):
        src(source_id="shop 12")
    with pytest.raises(ValidationError):
        src(kind="confluence_page", source_id="SHOP-12")
    assert src(kind="confluence_page", source_id="98765",
               url="https://acme-test.atlassian.net/wiki/spaces/ENG/pages/98765").key.endswith(":98765")
    with pytest.raises(ValidationError):
        src(url="https://example.com/browse/SHOP-12")
    with pytest.raises(ValidationError):
        src(content_hash="abc")
    with pytest.raises(ValidationError):
        src(version=0)


def test_the_same_text_gives_the_same_hash_whatever_the_spacing():
    assert m.content_hash("Wrong  password\nshows ‘x’") == m.content_hash("wrong password shows ‘x’")
    assert m.content_hash("8 characters") != m.content_hash("12 characters")


# ---------------------------------------------------------------- acceptance criteria

def test_a_criterion_taken_from_the_source_must_be_in_its_quote():
    assert ac().usable
    with pytest.raises(ValidationError, match="nothing may be invented"):
        ac(text="A wrong password locks the account after 3 tries.")
    with pytest.raises(ValidationError, match="expected_outcome"):
        ac(expected_outcome="the account is locked")


def test_gherkin_parts_are_also_checked_against_the_source():
    ok = ac(id="SHOP-12#AC-1", text="Given a registered user, when they enter a valid password, then the dashboard "
                                    "is shown.", given="a registered user", when="they enter a valid password",
            then="the dashboard is shown", expected_outcome="the dashboard is shown")
    assert ok.then == "the dashboard is shown"
    with pytest.raises(ValidationError):
        ac(id="SHOP-12#AC-1", text="Given a registered user", then="a welcome email is sent")


def test_an_ai_proposal_waits_for_a_named_reviewer():
    proposal = ac(text="Check that the error text is visible next to the password field.", expected_outcome="",
                  extraction="ai_proposed")
    assert proposal.review == m.ReviewStatus.needs_review and not proposal.usable
    with pytest.raises(ValidationError, match="named reviewer"):
        ac(text="Check the error text.", expected_outcome="", extraction="ai_proposed", review="accepted")
    accepted = ac(text="Check the error text.", expected_outcome="", extraction="ai_proposed", review="accepted",
                  reviewer="mani")
    assert accepted.usable


def test_the_ai_may_not_invent_an_expected_outcome():
    with pytest.raises(ValidationError, match="quoted from the source"):
        ac(text="Check lockout.", expected_outcome="the account is locked for 30 minutes", extraction="ai_proposed")
    assert ac(text="Check the message.", extraction="ai_proposed").expected_outcome


def test_a_criterion_needs_a_citation_and_an_unautomatable_one_a_reason():
    with pytest.raises(ValidationError):
        ac(citations=[])
    with pytest.raises(ValidationError, match="say why"):
        ac(automatable=False)
    manual = ac(automatable=False, not_automatable_reason="needs a real fingerprint sensor")
    assert not manual.automatable
    with pytest.raises(ValidationError):
        ac(not_automatable_reason="x")


def test_a_rejected_rule_criterion_is_not_used():
    assert not ac(review="rejected").usable


def test_criterion_ids_belong_to_their_requirement():
    with pytest.raises(ValidationError):
        ac(id="SHOP-99#AC-1")
    with pytest.raises(ValidationError):
        ac(id="SHOP-12-AC1")


# ---------------------------------------------------------------- requirement

def test_a_requirement_keeps_sources_criteria_and_tenant_together():
    page = src(kind="confluence_page", source_id="98765", connection_id="conf-main",
               url="https://acme-test.atlassian.net/wiki/spaces/ENG/pages/98765", content_hash=m.content_hash("x"))
    r = m.Requirement(id="SHOP-12", tenant_id="t1", title="Login", sources=[src(), page], criteria=[ac()])
    assert [s.kind.value for s in r.sources] == ["jira_issue", "confluence_page"]
    with pytest.raises(ValidationError, match="tenant"):
        m.Requirement(id="SHOP-12", tenant_id="t2", title="Login", sources=[src()])
    with pytest.raises(ValidationError, match="duplicate"):
        m.Requirement(id="SHOP-12", tenant_id="t1", title="Login", sources=[src()], criteria=[ac(), ac()])
    with pytest.raises(ValidationError, match="cites a source"):
        m.Requirement(id="SHOP-12", tenant_id="t1", title="Login", sources=[page],
                      criteria=[ac()])  # (cites the Jira issue, which is not among the sources)
    with pytest.raises(ValidationError):
        m.Requirement(id="SHOP-12", tenant_id="t1", title="Login", sources=[])


def test_a_conflict_cites_two_places_and_only_a_person_resolves_it():
    a = cite("Passwords have at least 8 characters.")
    b = cite("Passwords must be 12 characters or more.", source=src(kind="confluence_page", source_id="98765",
             url="https://acme-test.atlassian.net/wiki/spaces/ENG/pages/98765"), locator="h2: Password rules")
    c = m.Conflict(id="X1", tenant_id="t1", requirement_ids=["SHOP-12"], summary="minimum password length differs",
                   citations=[a, b], detected_by="rules")
    assert c.status == "open"
    with pytest.raises(ValidationError, match="two different places"):
        m.Conflict(id="X1", tenant_id="t1", requirement_ids=["SHOP-12"], summary="same place twice",
                   citations=[a, a], detected_by="ai")
    with pytest.raises(ValidationError, match="named person"):
        m.Conflict(id="X1", tenant_id="t1", requirement_ids=["SHOP-12"], summary="minimum password length differs",
                   citations=[a, b], detected_by="ai", status="resolved")


# ---------------------------------------------------------------- traceability

def link(**kw):
    base = {"tenant_id": "t1", "requirement_id": "SHOP-12", "criterion_id": "SHOP-12#AC-2",
                "source_key": "jira-main:jira_issue:SHOP-12", "source_version": 3, "tc_id": "TC-007", "platform": "web"}
    return m.TraceLink(**{**base, **kw})


def test_never_passed_without_a_run_and_evidence():
    assert link().result == m.TestResult.not_run
    for result in ("passed", "failed", "flaky"):
        with pytest.raises(ValidationError, match="evidence"):
            link(result=result)
        with pytest.raises(ValidationError, match="evidence"):
            link(result=result, evidence=["screenshots/TC-007.png"])  # (no run id)
    ok = link(result="passed", run_id="20261123_101500", evidence=["screenshots/TC-007.png", "trace/TC-007.zip"])
    assert ok.result == m.TestResult.passed
    with pytest.raises(ValidationError):
        link(run_id="20261123_101500")  # (not run, but with a run)


def test_not_automated_blocked_and_skipped_need_a_reason():
    for result in ("not_automated", "blocked", "skipped", "inconclusive"):
        with pytest.raises(ValidationError, match="reason"):
            link(result=result)
    assert link(result="not_automated", reason="needs a camera").reason


def test_evidence_stays_inside_the_run_folder_and_defects_are_issue_keys():
    for bad in ("/etc/passwd", "../other/x.png", "C:\\x.png", "a/../../x"):
        with pytest.raises(ValidationError):
            link(result="failed", run_id="r1", evidence=[bad])
    with pytest.raises(ValidationError):
        link(defect_keys=["not a key"])
    assert link(defect_keys=["SHOP-40"]).defect_keys == ["SHOP-40"]


def test_a_test_designed_from_an_older_version_is_stale():
    assert link().is_stale(4) and not link().is_stale(3)
    with pytest.raises(ValidationError):
        link(criterion_id="SHOP-13#AC-1")


# ---------------------------------------------------------------- sync and writes

def test_a_sync_cursor_resumes_and_never_keeps_a_token_in_its_error():
    c = m.SyncCursor(tenant_id="t1", connection_id="jira-main", scope="jql:project = SHOP", status="partial",
                     next_page_token="eyJwYWdl", fetched=100, failed_items=["SHOP-77"],
                     last_error="401 for token ATATT3xFfGF0abcdefghijklmnopqrstu")
    assert "ATATT" not in c.last_error and c.next_page_token
    with pytest.raises(ValidationError):
        m.SyncCursor(tenant_id="t1", connection_id="jira-main", scope="jql:x", status="complete", next_page_token="p")


def write(**kw):
    payload = kw.pop("payload", {"body": "Qpilot run 20261123_101500: TC-007 passed (SHOP-12#AC-2)."})
    op = m.WriteOperation(kw.pop("operation", "add_comment"))
    target = kw.pop("target", "SHOP-12")
    return m.OutboundWrite(tenant_id="t1", connection_id="jira-main", operation=op, target=target, payload=payload,
                           idempotency_key=m.idempotency_key("t1", op, target, payload), **kw)


def test_the_same_write_has_the_same_idempotency_key():
    a = write()
    assert a.idempotency_key == write().idempotency_key
    assert a.idempotency_key != write(payload={"body": "other"}).idempotency_key
    assert a.idempotency_key != m.idempotency_key("t2", m.WriteOperation.add_comment, "SHOP-12", a.payload)
    with pytest.raises(ValidationError, match="idempotency_key"):
        m.OutboundWrite(tenant_id="t1", connection_id="jira-main", operation="add_comment", target="SHOP-12",
                        payload={"body": "x"}, idempotency_key="0" * 64)


def test_a_new_jira_write_needs_a_named_approval_before_it_is_sent():
    assert write().status == m.WriteStatus.proposed
    for status in ("approved", "sent", "failed"):
        with pytest.raises(ValidationError, match="approved by a named person"):
            write(status=status)
    with pytest.raises(ValidationError, match="what Jira answered"):
        write(status="sent", approval_id="a1", approved_by="mani")
    assert write(status="sent", approval_id="a1", approved_by="mani", remote_id="10001").remote_id


def test_write_targets_and_payloads_are_checked():
    with pytest.raises(ValidationError):
        write(target="not-a-key")
    assert write(operation="create_issue", target="SHOP", payload={"summary": "x"}).target == "SHOP"
    with pytest.raises(ValidationError, match="credential"):
        write(payload={"body": "token ATATT3xFfGF0abcdefghijklmnop"})


# ---------------------------------------------------------------- privacy

def test_requirement_text_reaches_an_ai_only_as_the_privacy_settings_allow():
    C = m.Classification
    assert m.ai_use_allowed(C.confidential, privacy_mode="local", cloud_consent=False, provider_is_local=True)[0]
    assert not m.ai_use_allowed(C.public, privacy_mode="local", cloud_consent=False, provider_is_local=False)[0]
    assert not m.ai_use_allowed(C.public, privacy_mode="cloud", cloud_consent=False, provider_is_local=False)[0]
    assert m.ai_use_allowed(C.internal, privacy_mode="cloud", cloud_consent=True, provider_is_local=False)[0]
    assert not m.ai_use_allowed(C.confidential, privacy_mode="cloud", cloud_consent=True, provider_is_local=False,
                                connection=conn())[0]
    assert m.ai_use_allowed(C.confidential, privacy_mode="cloud", cloud_consent=True, provider_is_local=False,
                            connection=conn(allow_cloud_ai_for_confidential=True))[0]
