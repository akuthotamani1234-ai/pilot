"""Requirements Intelligence, Milestone 3: the Studio workspace (/requirements) in a real browser.

The real Studio server (uvicorn) runs on 127.0.0.1 with its stores in a temp folder and talks to the local mock
Atlassian site (tests/atlassian_mock.py). Every number and row on the page comes from the backend - nothing is
stubbed in the browser."""
import os
import socket
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from backend import approvals, audit_store, requirements_api as rapi
from backend.atlassian import credentials, store
from tests.atlassian_mock import EMAIL, T0, TOKEN, MockJira, story

AC = "Acceptance Criteria\n- Valid login opens the dashboard\n- A wrong password shows 'Invalid credentials'"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def studio(monkeypatch, tmp_path):
    import uvicorn

    from backend import server
    mock = MockJira()
    mock.projects = [{"id": "7", "key": "QPL", "name": "Qpilot shop"}]
    for i, (summary, t) in enumerate([("User Login Functionality", "Story"), ("Product Browsing and Sorting", "Story"),
                                      ("Shopping Cart Management", "Task")], 2):
        mock.issues[f"QPL-{i}"] = story(f"QPL-{i}", summary, T0 + timedelta(minutes=i), AC, "",
                                        issuetype={"name": t})
    monkeypatch.setattr(approvals, "DEFAULT_DB", tmp_path / "approvals.sqlite")
    monkeypatch.setattr(store, "DEFAULT_DB", tmp_path / "req.sqlite")
    monkeypatch.setattr(audit_store, "DEFAULT_DB", tmp_path / "audit.sqlite")
    monkeypatch.setattr(credentials, "DEFAULT_FILE", tmp_path / "creds.json")
    monkeypatch.setattr(rapi, "CLIENT_BASE_URL", mock.url)
    monkeypatch.setattr(rapi, "JOBS", rapi.Jobs())
    for key in ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_PROJECT", "JIRA_READ_API_TOKEN",
                "QPILOT_DASHBOARD_AUTH", "QPILOT_DASHBOARD_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)
    yield type("Studio", (), {"url": f"http://127.0.0.1:{port}", "mock": mock})
    srv.should_exit = True
    thread.join(10)
    mock.close()


def open_page(browser, studio, viewport=None):
    ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "favicon" not in m.text else None)
    page.goto(studio.url + "/requirements#overview")
    return ctx, page, errors


def connect_jira(page, site="https://aimaniforall1234-1795449805793.atlassian.net", token=TOKEN):
    page.goto(page.url.split("#")[0] + "#integrations")
    page.fill("#jiraSite", site)
    page.fill("#jiraEmail", EMAIL)
    page.fill("#jiraTypes", "Story, Task")
    page.fill("#jiraToken", token)
    page.get_by_role("button", name="Connect").first.click()
    expect(page.get_by_text("token saved")).to_be_visible()


def test_the_whole_workspace_from_connection_to_review(browser, studio):
    ctx, page, errors = open_page(browser, studio)
    try:
        # overview: empty, honest
        expect(page.locator("#stats")).to_contain_text("0requirements imported")
        expect(page.locator("#ovConnections")).to_contain_text("No site connected yet")
        expect(page.locator("#actions")).to_contain_text("Generate test cases")
        expect(page.locator("#actions .rq-coming")).to_have_count(4)  # (Phase 4 actions: labelled, not buttons)
        assert page.locator("#actions button").count() == 0
        # integrations: connect, the token is not kept anywhere in the page
        connect_jira(page)
        assert page.input_value("#jiraToken") == ""
        assert TOKEN not in page.content()
        assert TOKEN not in page.evaluate("JSON.stringify(localStorage) + JSON.stringify(sessionStorage)")
        page.get_by_role("button", name="Test connection").first.click()
        expect(page.get_by_text("Connected as QA Reader. 1 project visible. Read-only.")).to_be_visible()
        # import wizard: project, real types with counts, preview, untick one, import
        page.goto(studio.url + "/requirements#import")
        page.get_by_role("button", name="Next").first.click()
        expect(page.locator("#wProject")).to_contain_text("QPL — Qpilot shop")
        page.locator('[data-panel="2"] [data-next="3"]').click()
        expect(page.locator("#wTypes")).to_contain_text("Story (2)")
        expect(page.locator("#wTypes")).to_contain_text("Task (1)")
        page.locator('[data-panel="3"] [data-next="4"]').click()
        expect(page.locator("#pvSummary")).to_contain_text("3 work items shown of about 3. 3 new, 0 updated, 0 unchanged.")
        expect(page.locator("#pvTable tbody tr")).to_have_count(3)
        page.get_by_label("Import QPL-3").uncheck()
        assert page.locator("#pvAll").evaluate("(checkbox) => checkbox.indeterminate")
        page.route("**/api/requirements/imports/*", lambda route: route.fulfill(
            status=503, json={"detail": "Import status temporarily unavailable"}), times=1)
        page.click("#startImport")
        expect(page.locator("#impStatus")).to_have_text("Import status temporarily unavailable")
        errors[:] = [error for error in errors if "503 (Service Unavailable)" not in error]
        with page.expect_request(lambda request: request.method == "GET"
                                 and "/api/requirements/imports/" in request.url):
            page.click("#impRetry")
        expect(page.locator("#impStatus")).to_contain_text("Import complete")
        expect(page.locator("#impResult")).to_contain_text("2new")
        expect(page.locator("#impResult")).to_contain_text("4criteria found")
        assert studio.mock.issues  # (unticked QPL-3 was not imported:)
        page.click("#toAnalyze")
        page.click("#anRun")
        expect(page.locator("#anStatus")).to_contain_text("2 requirements analysed")
        # explorer
        page.goto(studio.url + "/requirements#explorer")
        expect(page.locator("#exTable tbody tr")).to_have_count(2)
        expect(page.locator("#exTable")).not_to_contain_text("QPL-3")
        expect(page.locator("#exTable tbody tr").first).to_contain_text("User Login Functionality")
        page.select_option("#exType", "Task")
        expect(page.locator("#exTable tbody tr")).to_have_count(1)
        expect(page.locator("#exTable tbody")).to_contain_text("QPL-4")
        page.select_option("#exType", "")
        page.fill("#exQ", "no such words anywhere")
        expect(page.locator("#exTable tbody")).to_contain_text("Nothing matches these filters.")
        page.fill("#exQ", "")
        expect(page.locator("#exTable tbody tr")).to_have_count(2)
        page.get_by_role("button", name="Open QPL-2").click()
        drawer = page.locator("#detail")
        expect(drawer).to_contain_text("Valid login opens the dashboard")
        expect(drawer).to_contain_text("QPL-2 v1 · description: acceptance criteria")
        page.get_by_role("tab", name="Analysis").click()
        expect(drawer).to_contain_text("Extracted acceptance criteria (2)")
        expect(drawer).to_contain_text("Missing requirements (0)")
        page.keyboard.press("ArrowRight")  # (arrow keys move between tabs)
        expect(page.get_by_role("tab", name="Test Cases")).to_have_attribute("aria-selected", "true")
        expect(drawer).to_contain_text("Upcoming · Phase 4")
        page.get_by_role("tab", name="Version History").click()
        expect(page.get_by_role("tab", name="Version History")).to_have_attribute("aria-selected", "true")
        expect(drawer).to_contain_text("v1")
        page.get_by_role("button", name="Close details").click()
        # review center: accept, edit, reject - signed as the local user
        page.goto(studio.url + "/requirements#reviews")
        expect(page.locator("#rvWho")).to_contain_text("local-user")
        cards = page.locator(".rq-review")
        before = cards.count()
        assert before >= 3
        first = cards.first.locator("h3").inner_text()
        cards.first.get_by_role("button", name="Accept").click()
        expect(cards).to_have_count(before - 1)
        cards.first.get_by_role("button", name="Edit").click()
        cards.first.locator("input[name=title]").fill("Login is refused with a wrong password (edited)")
        cards.first.get_by_role("button", name="Accept with changes").click()
        expect(cards).to_have_count(before - 2)
        cards.first.get_by_role("button", name="Reject").click()
        expect(cards).to_have_count(before - 3)
        page.select_option("#rvStatus", "accepted")
        expect(page.locator("#rvList")).to_contain_text(first)
        expect(page.locator("#rvList")).to_contain_text("Login is refused with a wrong password (edited)")
        expect(page.locator("#rvList")).to_contain_text("Corrected by local-user")
        page.select_option("#rvStatus", "rejected")
        expect(page.locator("#rvList")).to_contain_text("Rejected by local-user")
        # overview and history reflect the real data
        page.goto(studio.url + "/requirements#overview")
        expect(page.locator("#stats")).to_contain_text("2requirements imported")
        expect(page.locator("#stats")).to_contain_text("4acceptance criteria (analysed)")
        page.goto(studio.url + "/requirements#history")
        expect(page.locator("#hsTable tbody tr")).to_have_count(1)
        expect(page.locator("#hsTable tbody tr").first).to_contain_text("items")
        expect(page.locator("#auditList")).to_contain_text("token.set")
        assert not errors, errors
        assert not [r for r in studio.mock.requests if r["method"] not in ("GET", "POST")]
    finally:
        ctx.close()


def test_jira_text_is_shown_as_text_never_as_html(browser, studio):
    studio.mock.issues["QPL-2"]["fields"]["summary"] = "<img src=x onerror=window.__xss=1> Login"
    ctx, page, errors = open_page(browser, studio)
    try:
        connect_jira(page)
        page.goto(studio.url + "/requirements#import")
        page.click("input[value=items]")
        page.get_by_role("button", name="Next").first.click()
        page.fill("#wKeys", "QPL-2")
        page.locator('[data-panel="2"] [data-next="3"]').click()
        page.locator('[data-panel="3"] [data-next="4"]').click()
        expect(page.locator("#pvTable tbody")).to_contain_text("<img src=x onerror=window.__xss=1> Login")
        page.click("#startImport")
        expect(page.locator("#impStatus")).to_contain_text("Import complete")
        page.goto(studio.url + "/requirements#explorer")
        expect(page.locator("#exTable tbody")).to_contain_text("<img src=x")
        assert page.locator("#exTable img").count() == 0 and page.evaluate("window.__xss") is None
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("mode", ["incremental", "full", "jql", "items"])
def test_workspace_import_modes_in_chromium(browser, studio, mode):
    ctx, page, _ = open_page(browser, studio)
    try:
        connect_jira(page)
        page.get_by_role("button", name="Discover projects").click()
        expect(page.get_by_text("QPL — Qpilot shop")).to_be_visible()
        page.goto(studio.url + "/requirements#import")
        page.check(f'input[name=wMode][value="{mode}"]')
        page.locator('[data-panel="1"] [data-next="2"]').click()
        if mode == "items":
            page.get_by_text("Find work items by summary").click()
            expect(page.locator("#wProject")).to_have_value("QPL")
            page.fill("#issueQuery", "User Login")
            page.click("#findIssues")
            page.get_by_role("button", name="Add QPL-2 — User Login Functionality").click()
            expect(page.locator("#wKeys")).to_have_value("QPL-2")
        page.locator('[data-panel="2"] [data-next="3"]').click()
        if mode == "jql":
            page.fill("#fJql", 'status = "To Do"')
        page.locator('[data-panel="3"] [data-next="4"]').click()
        expect(page.locator("#pvTable tbody tr")).to_have_count(1 if mode == "items" else 3)
        page.click("#startImport")
        expect(page.locator("#impStatus")).to_contain_text("Import complete")
    finally:
        ctx.close()


def test_all_workspace_destinations_and_screenshots(browser, studio):
    ctx, page, errors = open_page(browser, studio)
    try:
        connect_jira(page, site="https://qpilot-demo.atlassian.net")
        browser_import = studio.url + "/requirements#import"
        page.goto(browser_import)
        page.check('input[name=wMode][value="items"]')
        page.locator('[data-panel="1"] [data-next="2"]').click()
        page.fill("#wKeys", "QPL-2")
        page.locator('[data-panel="2"] [data-next="3"]').click()
        page.locator('[data-panel="3"] [data-next="4"]').click()
        page.click("#startImport")
        expect(page.locator("#impStatus")).to_contain_text("Import complete")
        page.click("#toAnalyze")
        page.click("#anRun")
        expect(page.locator("#anStatus")).to_contain_text("1 requirement analysed")

        screenshots = os.environ.get("QPILOT_REQUIREMENTS_SCREENSHOTS")
        if screenshots:
            Path(screenshots).mkdir(parents=True, exist_ok=True)
        nav = page.locator(".rq-nav [data-view]")
        assert nav.count() == 16
        for link in nav.all():
            view = link.get_attribute("data-view")
            link.click()
            section = page.locator(f"#view-{view}")
            expect(section.get_by_role("heading", level=1)).to_be_visible()
            expect(link).to_have_attribute("aria-current", "page")
            page.wait_for_load_state("networkidle")
            if view in {"builder", "execution", "agents", "evidence", "traceability", "writeback"}:
                expect(section.get_by_text("Upcoming", exact=False)).to_be_visible()
            if view == "analysis":
                section.get_by_role("button", name="QPL-2 — User Login Functionality").click()
                expect(page.get_by_role("tab", name="AI Analysis")).to_have_attribute("aria-selected", "true")
                expect(page.locator("#dtBody")).to_contain_text("Extracted acceptance criteria")
                page.get_by_role("button", name="Close details").click()
            if view == "coverage":
                expect(section.get_by_role("rowheader", name="User Login Functionality")).to_be_visible()
            if view == "settings":
                expect(section).to_contain_text("Read-only")
            if screenshots:
                page.screenshot(path=Path(screenshots) / f"{view}.png", full_page=True)
        assert not errors, errors
    finally:
        ctx.close()


def test_jira_preview_counts_all_loaded_pages(browser, studio):
    for i in range(5, 53):
        key = f"QPL-{i}"
        studio.mock.issues[key] = story(key, f"Story {i}", T0 + timedelta(minutes=i), AC, "")
    ctx, page, _ = open_page(browser, studio)
    try:
        connect_jira(page)
        page.goto(studio.url + "/requirements#import")
        page.locator('[data-panel="1"] [data-next="2"]').click()
        page.locator('[data-panel="2"] [data-next="3"]').click()
        page.locator('[data-panel="3"] [data-next="4"]').click()
        expect(page.locator("#pvSummary")).to_contain_text("50 work items shown of about 51. 50 new")
        page.get_by_label("Import QPL-2", exact=True).uncheck()
        page.click("#pvMore")
        expect(page.locator("#pvSummary")).to_contain_text("51 work items shown of about 51. 51 new")
        expect(page.get_by_label("Import QPL-2", exact=True)).not_to_be_checked()
    finally:
        ctx.close()


def test_targeted_import_by_link_and_a_wrong_site_link_is_explained(browser, studio):
    ctx, page, errors = open_page(browser, studio)
    try:
        connect_jira(page)
        page.goto(studio.url + "/requirements#import")
        page.click("input[value=items]")
        page.get_by_role("button", name="Next").first.click()
        page.fill("#wKeys", "https://other.atlassian.net/browse/QPL-2")
        page.locator('[data-panel="2"] [data-next="3"]').click()
        page.locator('[data-panel="3"] [data-next="4"]').click()
        expect(page.locator("#banner")).to_contain_text("is not a link to aimaniforall1234-1795449805793.atlassian.net")
        expect(page.locator('[data-panel="3"]')).to_be_visible()  # (the wizard stays where it was)
        page.locator('[data-panel="3"] [data-next="2"]').click()
        page.fill("#wKeys", "https://aimaniforall1234-1795449805793.atlassian.net/browse/QPL-4, QPL-99")
        page.locator('[data-panel="2"] [data-next="3"]').click()
        page.locator('[data-panel="3"] [data-next="4"]').click()
        expect(page.locator("#pvSummary")).to_contain_text("Not found or not permitted: QPL-99: not_found")
        page.click("#startImport")
        expect(page.locator("#impStatus")).to_contain_text("Import complete")
        expect(page.locator("#impResult")).to_contain_text("1new")
    finally:
        ctx.close()


def test_a_refused_token_gets_a_clear_message(browser, studio):
    ctx, page, errors = open_page(browser, studio)
    try:
        connect_jira(page, token="a-revoked-token-value-551")
        page.get_by_role("button", name="Test connection").first.click()
        expect(page.locator(".rq-conn").first).to_contain_text("replace it (Atlassian tokens expire or can be revoked)")
        assert "a-revoked-token-value-551" not in page.content()
    finally:
        ctx.close()


def test_empty_states_explain_the_next_step(browser, studio):
    ctx, page, errors = open_page(browser, studio)
    try:
        for view, text in (("explorer", "No requirements imported yet."), ("reviews", "Nothing waiting for review."),
                           ("confluence", "No Confluence pages imported yet."), ("history", "No imports yet.")):
            page.goto(studio.url + f"/requirements#{view}")
            expect(page.locator(f"#view-{view}")).to_contain_text(text)
        page.goto(studio.url + "/requirements#import")
        expect(page.locator("#wConnHelp")).to_contain_text("Connect Jira first")
        assert page.get_by_role("button", name="Next").first.is_disabled()
        assert not errors, errors
    finally:
        ctx.close()


def test_every_control_has_a_name_and_the_page_fits_a_phone(browser, studio):
    ctx, page, errors = open_page(browser, studio, {"width": 390, "height": 844})
    try:
        connect_jira(page)
        views = page.locator(".rq-nav [data-view]").evaluate_all("(links) => links.map(link => link.dataset.view)")
        assert len(views) == 16
        for view in views:
            page.goto(studio.url + f"/requirements#{view}")
            page.wait_for_load_state("networkidle")
            wide = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert wide <= 1, f"{view} scrolls sideways by {wide}px"
            unnamed = page.evaluate("""() => [...document.querySelectorAll('main input, main select, main textarea, main button')]
                .filter(el => el.offsetParent !== null)
                .filter(el => !(el.labels && el.labels.length) && !el.getAttribute('aria-label') && !el.textContent.trim()
                              && !el.getAttribute('aria-labelledby') && !el.title)
                .map(el => el.outerHTML.slice(0, 80))""")
            assert unnamed == [], f"{view}: {unnamed}"
        page.goto(studio.url + "/requirements")
        page.keyboard.press("Tab")
        expect(page.locator(".rq-skip")).to_be_focused()
        assert not errors, errors
    finally:
        ctx.close()


def test_with_studio_login_on_the_page_asks_to_sign_in_and_hides_review_buttons_from_viewers(
        browser, studio, monkeypatch, tmp_path):
    import backend.tenancy_store as tenancy
    monkeypatch.setattr(tenancy, "DEFAULT_DB", tmp_path / "tenancy.sqlite")
    tenancy.upsert_tenant("t1", "One")
    tenancy.upsert_principal("viewer-1", "t1", "v@ex.test", "viewer")
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    ctx, page, errors = open_page(browser, studio)
    try:
        expect(page.locator("#signin")).to_be_visible()
        page.fill("#signinToken", "viewer-1")
        page.get_by_role("button", name="Continue").click()
        expect(page.locator("#who")).to_contain_text("Signed in as viewer-1 · t1")
        assert "viewer-1" not in page.evaluate("JSON.stringify(localStorage) + JSON.stringify(sessionStorage)")
        page.goto(studio.url + "/requirements#reviews")
        expect(page.locator("#rvWho")).to_contain_text("decisions need a named, signed-in reviewer")
        expect(page.locator("#rvList")).to_contain_text("Nothing waiting for review.")
        page.reload()  # (a reload: the in-memory sign-in is gone)
        expect(page.locator("#signin")).to_be_visible()
    finally:
        ctx.close()


def test_the_studio_and_lab_link_to_the_workspace(browser, studio):
    ctx, page, errors = open_page(browser, studio)
    try:
        for path in ("/", "/qa-lab"):
            page.goto(studio.url + path)
            expect(page.locator('a.studio-nav[href="/requirements"]')).to_be_visible()
        page.click('a.studio-nav[href="/requirements"]')
        expect(page).to_have_url(studio.url + "/requirements")
        expect(page.locator("#view-overview h1")).to_have_text("Your Jira and Confluence requirements")
    finally:
        ctx.close()


def test_the_confluence_explorer_shows_spaces_headings_requirement_sections_and_stories(browser, studio):
    studio.mock.add_page("900", "Login specification",
                         "<h1>Login</h1><p>Background.</p><h2>Business rules</h2><ul><li>Passwords must have at "
                         "least 8 characters.</li></ul><p>See QPL-2 for the story.</p>")
    ctx, page, errors = open_page(browser, studio)
    try:
        connect_jira(page)
        page.fill("#confluenceSite", "https://aimaniforall1234-1795449805793.atlassian.net")
        page.fill("#confluenceEmail", EMAIL)
        page.fill("#confluenceToken", TOKEN)
        page.locator('section[aria-label="Confluence Cloud"]').get_by_role("button", name="Connect").click()
        expect(page.locator('section[aria-label="Confluence Cloud"]')).to_contain_text("token saved")
        page.get_by_role("button", name="Discover spaces").click()
        page.get_by_role("button", name="Import space ENG").click()
        expect(page.locator("#impStatus")).to_contain_text("Import complete")
        page.goto(studio.url + "/requirements#confluence")
        expect(page.locator("#cfSpaces")).to_contain_text("ENG (1)")
        page.get_by_role("button", name="Login specification").click()
        box = page.locator("#cfPage")
        expect(box).to_contain_text("Confluence version 1")
        expect(box).to_contain_text("Login › Business rules")
        expect(box.locator(".rq-section.req")).to_contain_text("requirement section")
        expect(box).to_contain_text("Passwords must have at least 8 characters.")
        expect(box).to_contain_text("Criteria taken from this page (1)")
        assert not errors, errors
    finally:
        ctx.close()
