"""Requirements Intelligence, Phase 3: acceptance criteria, quality issues, conflicts, suggestions, review, coverage.

Sources are built with the mock site's own builders (tests/atlassian_mock.py) and stored; the AI is a stub."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from backend import approvals, audit_store, privacy
from backend.atlassian import analysis as an, confluence, jira, store
from backend.atlassian.models import Basis, Connection, Coverage, IssueKind, ReviewStatus, ScenarioKind
from backend.config import settings
from tests.atlassian_mock import T0, adf, page, story

HOST = "acme-test.atlassian.net"
LATER = T0 + timedelta(days=3)
STORY_AC = """1. Given a registered user, when they enter a valid password, then the dashboard is shown.
2. A wrong password shows 'Invalid credentials'.
3. Passwords must have at least 8 characters.
4. Lock the account after 3 wrong tries."""
SPEC = ("<h1>Login</h1><p>Background text that is not a rule.</p>"
        "<h2>Business rules</h2><ul><li>Passwords must have at least 12 characters.</li>"
        "<li>Lock the account after 3 wrong tries.</li><li>The login page loads fast.</li></ul>"
        "<table><tbody><tr><th>Field</th><th>Rule</th></tr><tr><td>Email</td><td>is required</td></tr></tbody></table>"
        '<h2>Scenarios</h2><ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[Scenario: remember me\n'
        "Given a user who ticked remember me\nWhen they come back\nThen they are still logged in]]>"
        "</ac:plain-text-body></ac:structured-macro>")


def conn(product, tenant="t1", **kw):
    return Connection(id="jira-main" if product == "jira" else "conf-main", tenant_id=tenant, product=product,
                      site_url=f"https://{HOST}", email="qa@acme.test", token_ref="JIRA_READ_API_TOKEN", **kw)


@pytest.fixture
def db(tmp_path):
    d = store.connect(tmp_path / "req.sqlite")
    yield d
    d.close()


@pytest.fixture
def paths(tmp_path):
    return SimpleNamespace(approvals=tmp_path / "approvals.sqlite", audit=tmp_path / "audit.sqlite")


def put_story(db, key="SHOP-12", ac=STORY_AC, description="As a shopper I want to log in.", tenant="t1", **fields):
    c = conn("jira", tenant)
    store.save_connection(db, c)
    issue = story(key, "Login", T0, description, "", **fields)
    issue["fields"]["customfield_10045"] = adf(*ac.split("\n")) if ac else None
    item = jira.normalize(issue, c, ac_field="customfield_10045", retrieved_at=T0)
    store.upsert_source(db, item["source"], item["story"])
    return f"jira-main:jira_issue:{key}"


def put_page(db, page_id="900", body=SPEC, version=1, tenant="t1", title="Login spec", link_from="", **conn_kw):
    c = conn("confluence", tenant, **conn_kw)
    store.save_connection(db, c)
    item = confluence.normalize(page(page_id, title, body, version=version, when=T0 + timedelta(hours=version)), c,
                                space_key="ENG", retrieved_at=T0)
    store.upsert_source(db, item["source"], item["content"], native_version=True)
    key = f"conf-main:confluence_page:{page_id}"
    if link_from:
        store.save_link(db, tenant, link_from, key, "specified_by", "jira remote link")
    return key


def run(db, paths, key, **kw):
    return an.analyze(db, kw.pop("tenant", "t1"), key, approvals_db=paths.approvals, audit_db=paths.audit, now=LATER,
                      actor="mani", **kw)


def by_text(analysis, words):
    return next(c for c in analysis.requirement.criteria if words in c.text)


# ---------------------------------------------------------------- 1 extraction

def test_criteria_are_copied_from_the_jira_field_with_source_version_and_quote(db, paths):
    key = put_story(db)
    a = run(db, paths, key)
    texts = [c.text for c in a.requirement.criteria]
    assert texts == ["Given a registered user, when they enter a valid password, then the dashboard is shown.",
                     "A wrong password shows 'Invalid credentials'.", "Passwords must have at least 8 characters.",
                     "Lock the account after 3 wrong tries."]
    first = a.requirement.criteria[0]
    assert (first.given, first.when, first.then) == ("a registered user", "they enter a valid password",
                                                     "the dashboard is shown")
    for c in a.requirement.criteria:
        cit = c.citations[0]
        assert cit.source.key == key and cit.source.version == 1 and cit.locator == "customfield_10045"
        assert c.text in cit.quote.replace("\n", " ") or c.text.rstrip(".") in cit.quote
        assert c.extraction.value == "rules" and c.id.startswith("SHOP-12#AC-")


def test_without_the_field_only_the_acceptance_part_of_the_description_is_read(db, paths):
    key = put_story(db, ac="", description="As a shopper I log in.\n# Acceptance criteria\n- Errors are shown in red\n"
                                           "- The email field is required\n# Notes\n- Design by the agency")
    put = [c.text for c in run(db, paths, key).requirement.criteria]
    assert put == ["Errors are shown in red", "The email field is required"]
    assert run(db, paths, key).requirement.criteria[0].citations[0].locator == "description: acceptance criteria"


def test_multi_line_gherkin_scenarios_are_one_criterion_each(db, paths):
    key = put_story(db, ac="Scenario: lockout\nGiven a user\nWhen they fail 3 times\nThen the account is locked\n"
                           "And an email is sent\nScenario: unlock\nGiven a locked user\nWhen an admin unlocks\n"
                           "Then they can log in")
    crits = run(db, paths, key).requirement.criteria
    assert len(crits) == 2 and crits[0].then.lower().startswith("the account is locked")
    assert crits[1].given == "a locked user" and crits[1].expected_outcome == "they can log in"


def test_requirement_sections_of_a_linked_page_become_criteria(db, paths):
    key = put_story(db)
    page_key = put_page(db, link_from=key)
    a = run(db, paths, key)
    from_page = [c for c in a.requirement.criteria if c.citations[0].source.key == page_key]
    texts = [c.text for c in from_page]
    assert "Background text that is not a rule." not in texts
    assert "Passwords must have at least 12 characters." in texts and "Email | is required" in texts
    table = next(c for c in from_page if c.text == "Email | is required")
    assert table.citations[0].quote == "Field | Rule\nEmail | is required"
    assert table.citations[0].locator == "section: Login > Business rules (table)"
    gherkin = next(c for c in from_page if "remember me" in c.text)
    assert gherkin.then == "they are still logged in" and gherkin.citations[0].source.version == 1


# ---------------------------------------------------------------- 2 quality and conflicts

def test_ambiguous_incomplete_duplicate_and_contradictory_criteria_are_found(db, paths):
    key = put_story(db, ac="The page loads fast\nTBD: remember me\nGiven a cart\nWhen I pay\n"
                           "Users can delete their account\nUsers cannot delete their account\n"
                           "Show the order number\nShow the order number")
    a = run(db, paths, key)
    kinds = {(q.kind, tuple(q.criterion_ids)) for q in a.issues}
    ids = {c.text: c.id for c in a.requirement.criteria}
    assert (IssueKind.ambiguous, (ids["The page loads fast"],)) in kinds
    assert (IssueKind.incomplete, (ids["TBD: remember me"],)) in kinds
    assert any(q.kind == IssueKind.incomplete and "without a Then" in q.detail for q in a.issues)
    assert (IssueKind.contradictory, (ids["Users can delete their account"], ids["Users cannot delete their account"])) in kinds
    assert any(q.kind == IssueKind.duplicate for q in a.issues)


def test_a_story_without_criteria_gets_none_invented(db, paths):
    key = put_story(db, ac="", description="As a shopper I want a wish list.")
    a = run(db, paths, key)
    assert a.requirement.criteria == [] and a.suggestions == []
    assert [q.kind for q in a.issues] == [IssueKind.missing_criteria] and "none were invented" in a.issues[0].detail


def test_jira_and_confluence_conflicts_carry_both_quotes(db, paths):
    key = put_story(db)
    put_page(db, link_from=key)
    a = run(db, paths, key)
    conflict = next(x for x in a.conflicts if "characters" in x.summary)
    assert "8 vs 12" in conflict.summary
    sources = {c.source.kind.value: c.quote for c in conflict.citations}
    assert "at least 8 characters" in sources["jira_issue"] and "at least 12 characters" in sources["confluence_page"]
    dup = [q for q in a.issues if q.kind == IssueKind.duplicate]
    assert dup and "linked page" in dup[0].detail  # ('Lock the account after 3 wrong tries' in both)
    assert a.coverage[by_text(a, "at least 8").id] == Coverage.blocked  # (open conflict)
    assert not [s for s in a.suggestions if by_text(a, "at least 8").id in s.criterion_ids]
    story_lock, page_lock = [c.id for c in a.requirement.criteria if c.text == "Lock the account after 3 wrong tries."]
    shared = next(s for s in a.suggestions if s.kind == ScenarioKind.positive and story_lock in s.criterion_ids)
    assert page_lock in shared.criterion_ids and a.coverage[page_lock] == Coverage.pending_review


# ---------------------------------------------------------------- 3 suggestions and review

def test_rule_suggestions_say_what_is_explicit_and_what_is_inferred(db, paths):
    key = put_story(db)
    a = run(db, paths, key)
    eight = by_text(a, "at least 8")
    mine = [s for s in a.suggestions if eight.id in s.criterion_ids]
    kinds = {s.kind: s for s in mine}
    assert kinds[ScenarioKind.positive].basis == Basis.explicit
    assert kinds[ScenarioKind.positive].expected_outcome in kinds[ScenarioKind.positive].support_quote.replace("\n", " ")
    assert kinds[ScenarioKind.negative].basis == Basis.inferred and kinds[ScenarioKind.negative].expected_outcome == ""
    assert kinds[ScenarioKind.boundary].steps == ["Use 7 characters", "Use 8 characters"]
    # no generic 'security around' idea for a criterion that states no security rule (26 Nov 2026: such ideas were
    # automated as copies of the positive check and 'passed' without checking anything)
    assert ScenarioKind.security not in kinds
    assert all(s.review == ReviewStatus.needs_review and s.origin == "rules" for s in a.suggestions)
    queued = approvals.list_approvals(tenant_id="t1", path=paths.approvals, limit=200)
    assert {q["kind"] for q in queued} == {"requirement_suggestion"} and len(queued) == len(a.suggestions)


def test_a_security_rule_the_criterion_states_gets_an_explicit_security_idea(db, paths):
    key = put_story(db, ac="After 3 failed attempts the account is locked for 30 minutes")
    a = run(db, paths, key)
    sec = [s for s in a.suggestions if s.kind == ScenarioKind.security]
    assert len(sec) == 1 and sec[0].basis == Basis.explicit and sec[0].title.startswith("Verify the security rule")
    assert sec[0].expected_outcome and "states a security rule" in sec[0].note


def test_an_unautomatable_criterion_is_blocked_with_its_reason(db, paths):
    key = put_story(db, ac="Scan the QR code on the receipt to open the order\nThe totals are checked manually")
    a = run(db, paths, key)
    assert all(not c.automatable for c in a.requirement.criteria)
    assert {a.coverage[c.id] for c in a.requirement.criteria} == {Coverage.blocked}
    assert "real phone" in a.coverage_reason[a.requirement.criteria[0].id] and a.suggestions == []


def test_review_through_the_approval_queue_sets_coverage_and_survives_re_analysis(db, paths):
    key = put_story(db, ac="A wrong password shows 'Invalid credentials'.")
    a = run(db, paths, key)
    cid = a.requirement.criteria[0].id
    assert a.coverage[cid] == Coverage.pending_review
    positive = next(s for s in a.suggestions if s.kind == ScenarioKind.positive)
    with pytest.raises(ValueError):
        an.review(db, "t1", "SHOP-12", positive.id, "accept", "", approvals_db=paths.approvals)
    done = an.review(db, "t1", "SHOP-12", positive.id, "accept", "mani", approvals_db=paths.approvals,
                     audit_db=paths.audit)
    assert done.review == ReviewStatus.accepted and done.reviewer == "mani"
    row = next(r for r in approvals.list_approvals(status="accepted", tenant_id="t1", path=paths.approvals))
    assert row["id"] == positive.approval_id
    assert store.get_analysis(db, "t1", "SHOP-12").coverage[cid] == Coverage.covered
    before = len(approvals.list_approvals(status="pending", tenant_id="t1", path=paths.approvals, limit=200))
    again = run(db, paths, key)
    assert next(s for s in again.suggestions if s.id == positive.id).review == ReviewStatus.accepted
    assert len(approvals.list_approvals(status="pending", tenant_id="t1", path=paths.approvals, limit=200)) == before
    events = [h["event"] for h in store.analysis_history(db, "t1", "SHOP-12")]
    assert events[0].startswith("analyzed") and any("accepted by mani" in e for e in events)


def test_rejecting_every_idea_leaves_the_criterion_uncovered(db, paths):
    key = put_story(db, ac="A wrong password shows 'Invalid credentials'.")
    a = run(db, paths, key)
    for s in a.suggestions:
        an.review(db, "t1", "SHOP-12", s.id, "reject", "mani", approvals_db=paths.approvals)
    assert store.get_analysis(db, "t1", "SHOP-12").coverage[a.requirement.criteria[0].id] == Coverage.uncovered


def test_ambiguous_or_disputed_criteria_get_no_test_ideas_until_clarified(db, paths):
    key = put_story(db, ac="The search is fast\nThe search shows 20 results per page")
    a = run(db, paths, key)
    vague, clear = a.requirement.criteria
    assert a.coverage[vague.id] == Coverage.ambiguous and "clarify" in a.coverage_reason[vague.id]
    assert not [s for s in a.suggestions if vague.id in s.criterion_ids]
    assert [s for s in a.suggestions if clear.id in s.criterion_ids]


# ---------------------------------------------------------------- AI: privacy and hallucination prevention

def allow_ai(monkeypatch, mode="cloud", consent=True, provider="openai"):
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(privacy, "runtime_mode", lambda: mode)
    monkeypatch.setattr(privacy, "load_policy", lambda: SimpleNamespace(cloud_consent=consent))


class StubAI:
    def __init__(self, ideas):
        self.ideas, self.prompts = ideas, []

    def __call__(self, prompt, shape, **kw):
        self.prompts.append(prompt)
        from pydantic import TypeAdapter
        return TypeAdapter(shape).validate_python(self.ideas)


def test_ai_ideas_are_checked_and_never_change_the_criteria(db, paths, monkeypatch):
    allow_ai(monkeypatch)
    key = put_story(db, ac="A wrong password shows 'Invalid credentials'.\nPasswords must have at least 8 characters.")
    ai = StubAI([
        {"criterion_ids": ["SHOP-12#AC-1"], "kind": "negative", "title": "Wrong password message",
         "steps": ["Enter a wrong password"], "expected_outcome": "shows 'Invalid credentials'"},
        {"criterion_ids": ["SHOP-12#AC-2"], "kind": "boundary", "title": "Lockout after 7 characters",
         "steps": ["Type 7 characters"], "expected_outcome": "the account is locked for 30 minutes"},
        {"criterion_ids": ["SHOP-12#AC-9"], "kind": "positive", "title": "A criterion that does not exist"},
        {"criterion_ids": ["SHOP-12#AC-1"], "kind": "security", "title": "Log in as John Doe",
         "steps": ["Use the account of John Doe"]},
        {"criterion_ids": ["SHOP-12#AC-2"], "kind": "negative", "title": "Delete the account with a short password",
         "steps": ["delete the account"]}])
    before = [c.model_dump() for c in run(db, paths, key).requirement.criteria]
    a = run(db, paths, key, ai="auto", ask=ai, instructions="Focus on boundary cases")
    assert "Focus on boundary cases" in ai.prompts[0]
    assert a.ai == "used" and [c.model_dump() for c in a.requirement.criteria] == before
    from_ai = {s.title: s for s in a.suggestions if s.origin == "ai"}
    assert set(from_ai) == {"Wrong password message", "Lockout after 7 characters",
                            "Delete the account with a short password"}  # (unknown criterion, invented person: out)
    assert from_ai["Wrong password message"].basis == Basis.explicit
    assert from_ai["Lockout after 7 characters"].basis == Basis.inferred  # ('30 minutes' is not in the source)
    assert from_ai["Delete the account with a short password"].destructive == "delete"
    assert "qa@acme.test" not in ai.prompts[0] and "JIRA_READ_API_TOKEN" not in ai.prompts[0]


def test_local_privacy_mode_keeps_requirements_away_from_cloud_ai(db, paths, monkeypatch):
    allow_ai(monkeypatch, mode="local")
    key = put_story(db)
    ai = StubAI([])
    a = run(db, paths, key, ai="auto", ask=ai)
    assert a.ai == "not_allowed" and "local only" in a.ai_note and not ai.prompts
    assert a.requirement.criteria and a.suggestions  # (rules still work)


def test_cloud_ai_needs_consent_and_confidential_needs_explicit_permission(db, paths, monkeypatch):
    key = put_story(db)
    allow_ai(monkeypatch, consent=False)
    assert run(db, paths, key, ai="auto", ask=StubAI([])).ai == "not_allowed"
    allow_ai(monkeypatch)
    store.save_connection(db, conn("jira", classification="confidential"))
    ai = StubAI([])
    a = run(db, paths, key, ai="auto", ask=ai)
    assert a.ai == "not_allowed" and "confidential" in a.ai_note and not ai.prompts
    store.save_connection(db, conn("jira", classification="confidential", allow_cloud_ai_for_confidential=True))
    assert run(db, paths, key, ai="auto", ask=StubAI([])).ai == "used"


def test_a_local_model_is_allowed_and_no_provider_means_rules_only(db, paths, monkeypatch):
    key = put_story(db)
    allow_ai(monkeypatch, mode="local", provider="ollama")
    monkeypatch.setattr(settings, "ollama_url", "http://127.0.0.1:11434")
    assert run(db, paths, key, ai="auto", ask=StubAI([])).ai == "used"
    allow_ai(monkeypatch, provider="none")
    assert run(db, paths, key, ai="auto", ask=StubAI([])).ai == "not_allowed"


def test_an_ai_failure_keeps_the_rules_result(db, paths, monkeypatch):
    allow_ai(monkeypatch)
    key = put_story(db)

    def broken(*a, **k):
        raise TimeoutError("no answer")
    a = run(db, paths, key, ai="auto", ask=broken)
    assert a.ai == "failed" and a.suggestions and all(s.origin == "rules" for s in a.suggestions)


# ---------------------------------------------------------------- staleness, tenants, audit, originals

def test_a_newer_source_version_makes_the_analysis_stale(db, paths):
    key = put_story(db)
    page_key = put_page(db, link_from=key)
    a = run(db, paths, key)
    assert an.stale(db, "t1", a) == []
    put_page(db, body=SPEC.replace("12 characters", "10 characters"), version=2)
    assert an.stale(db, "t1", a) == [f"{page_key} changed: version 1 -> 2"]
    put_page(db, page_id="901", body="<h2>Rules</h2><p>Must log out after 15 minutes.</p>", title="Session",
             link_from=key)
    assert any("901 was linked after the analysis" in r for r in an.stale(db, "t1", a))
    store.mark_source_missing(db, "t1", page_key)
    assert any("no longer visible" in r for r in an.stale(db, "t1", a))
    fresh = run(db, paths, key)
    assert fresh.source_versions[page_key] == 2 and an.stale(db, "t1", fresh) == []
    assert fresh.coverage[by_text(fresh, "10 characters").id] == Coverage.blocked  # (its page is gone)


def test_tenants_are_isolated(db, paths):
    key = put_story(db)
    run(db, paths, key)
    assert store.get_analysis(db, "t2", "SHOP-12") is None
    with pytest.raises(LookupError):
        run(db, paths, key, tenant="t2")
    a = store.get_analysis(db, "t1", "SHOP-12")
    with pytest.raises(PermissionError):
        approvals.decide_approval(a.suggestions[0].approval_id, "accept", tenant_id="t2", path=paths.approvals)
    with pytest.raises(LookupError):
        an.review(db, "t2", "SHOP-12", a.suggestions[0].id, "accept", "eve", approvals_db=paths.approvals)


def test_analysis_is_audited_and_leaves_the_original_content_untouched(db, paths):
    key = put_story(db)
    page_key = put_page(db, link_from=key)
    before = (store.get_source(db, "t1", key)["content"], store.get_source(db, "t1", page_key)["content"],
              len(store.history(db, "t1", key)))
    run(db, paths, key)
    after = (store.get_source(db, "t1", key)["content"], store.get_source(db, "t1", page_key)["content"],
             len(store.history(db, "t1", key)))
    assert before == after
    audits = audit_store.list_audits(tenant_id="t1", db_path=paths.audit)
    assert audits and audits[0]["action"] == "requirements.analyze"


def test_a_page_can_be_analysed_on_its_own(db, paths):
    key = put_page(db)
    a = run(db, paths, key)
    assert a.requirement.id == "conf-900" and a.requirement.kind == "spec"
    assert all(c.id.startswith("conf-900#AC-") for c in a.requirement.criteria)
    summary = an.summary(a)
    assert summary["criteria"][0]["from"].startswith("900 v1 · section: Login > Business rules")


def test_end_to_end_on_the_mock_site_analysis_sends_nothing_to_atlassian(db, paths):
    from backend.atlassian.client import Client
    from backend.atlassian.sync import link_story, sync_confluence_space, sync_jira
    from tests.atlassian_mock import TOKEN, MockAtlassian
    mock = MockAtlassian()
    try:
        mock.issues["SHOP-12"] = story("SHOP-12", "Login", T0, "As a shopper I log in.", STORY_AC.replace("\n", " "))
        mock.issues["SHOP-12"]["fields"]["customfield_10045"] = adf(*STORY_AC.split("\n"))
        mock.remote_links["SHOP-12"] = [{"globalId": "appId=x&pageId=900", "object": {"url": "", "title": "spec"}}]
        mock.add_page("900", "Login spec", SPEC)
        jc, cc = conn("jira"), conn("confluence")
        store.save_connection(db, jc)
        store.save_connection(db, cc)

        def cl(c):
            return Client(c, base_url=mock.url, secret=lambda n: TOKEN, sleep=lambda s: None)
        sync_jira(db, jc, cl(jc), tenant_id="t1", project="SHOP", audit_db=paths.audit, now=LATER)
        sync_confluence_space(db, cc, cl(cc), tenant_id="t1", space_key="ENG", audit_db=paths.audit, now=LATER)
        link_story(db, jc, cl(jc), cc, cl(cc), tenant_id="t1", issue_key="SHOP-12", audit_db=paths.audit, now=LATER)
        sent = len(mock.requests)
        a = run(db, paths, "jira-main:jira_issue:SHOP-12")
        assert len(mock.requests) == sent  # (analysis reads only the local store)
        assert {r["method"] for r in mock.requests} <= {"GET", "POST"}
        assert all(r["path"] == "/rest/api/3/search/jql" for r in mock.requests if r["method"] == "POST")
        assert {s.kind.value for s in a.requirement.sources} == {"jira_issue", "confluence_page"}
        assert any("8 vs 12" in x.summary for x in a.conflicts)
    finally:
        mock.close()
