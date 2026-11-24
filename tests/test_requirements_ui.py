"""Requirements Intelligence, Milestone 3: the Studio workspace (/requirements) in a real browser.

The real Studio server (uvicorn) runs on 127.0.0.1 with its stores in a temp folder and talks to the local mock
Atlassian site (tests/atlassian_mock.py). Every number and row on the page comes from the backend - nothing is
stubbed in the browser."""
import os
import re
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
        expect(page.locator("#actions .rq-coming")).to_have_count(0)
        expect(page.locator("#actions a[href='#writeback']")).to_contain_text("Jira writes are off")
        expect(page.locator("#actions a[href='#builder']")).to_contain_text("Generate test cases")
        expect(page.locator("#actions a[href='#execution']")).to_contain_text("Run tests")
        expect(page.locator("#actions a[href='#traceability']")).to_contain_text("View traceability")
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
        expect(drawer).to_contain_text("No test cases yet")
        expect(drawer.get_by_role("button", name="Generate from accepted ideas")).to_be_visible()
        expect(drawer).not_to_contain_text("Upcoming")
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
        nxt = page.locator("#rvNext")  # (next actions after an acceptance)
        expect(nxt).to_contain_text("Accepted for QPL-2. Next:")
        nxt.get_by_role("button", name="Generate test cases for QPL-2").click()
        expect(nxt).to_contain_text("2 test cases for QPL-2 (2 new)")
        expect(nxt.get_by_role("link", name="Configure and run")).to_have_attribute("href", "#execution")
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
        page.goto(studio.url + "/requirements#history")  # (audit times are ISO text: shown as a date, never '—')
        first_time = page.locator("#auditList time").first
        expect(first_time).not_to_have_text("—")
        expect(first_time).to_have_text(re.compile(r"\d{4}|\d{1,2}/\d{1,2}"))
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
            if view == "writeback":
                expect(section.locator("#wbState")).to_contain_text("off (QPILOT_JIRA_WRITEBACK=1 not set)")
                expect(section.locator("#wbState")).to_contain_text("not stored")
            if view in {"builder", "execution", "agents", "evidence", "traceability", "writeback"}:
                expect(section).not_to_contain_text("Upcoming")
            if view == "execution":
                expect(section.locator("#exAuth")).not_to_be_checked()
                assert section.locator("#xcApp option[value=android]").get_attribute("disabled") is not None
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


def test_builder_execution_results_and_traceability_in_chromium(browser, studio, monkeypatch, tmp_path):
    """Phase 4 in the browser: accepted ideas -> generated test cases -> a run of the selected case -> its real
    result (read from the run's test_cases.json) in the Execution Center, the traceability matrix and the drawer.
    The run launcher is replaced (the real one starts main.py; the live end-to-end run covers it)."""
    import json
    from urllib.parse import quote

    import httpx

    from backend import server
    h = {"X-Agentic-QA": "1"}
    with httpx.Client(base_url=studio.url, headers=h, timeout=30) as c:
        assert c.post("/api/requirements/connections", json={
            "id": "jira-main", "product": "jira", "site_url": "https://aimaniforall1234-1795449805793.atlassian.net",
            "email": EMAIL}).status_code == 200
        c.put("/api/requirements/connections/jira-main/token", json={"token": TOKEN})
        job = c.post("/api/requirements/connections/jira-main/imports", json={"mode": "items", "keys": "QPL-2"}).json()
        rapi.JOBS.wait(job["id"])
        analysis = c.post("/api/requirements/items/jira-main/QPL-2/analyze", json={}).json()["analysis"]
        for s in analysis["suggestions"][:2]:
            c.post(f"/api/requirements/items/jira-main/QPL-2/suggestions/{quote(s['id'], safe='')}/review",
                   json={"answer": "yes"})
    launched = {}

    def fake_launch(req, caller):
        launched["req"] = req
        server.jobs[5151] = {"id": 5151, "status": "running", "run": ""}
        return {"id": 5151}
    monkeypatch.setattr(server, "_launch_run", fake_launch)
    ctx, page, errors = open_page(browser, studio)
    try:
        page.goto(studio.url + "/requirements#builder")
        page.locator("#genReq").select_option(index=0)
        page.locator("#genForm button").click()
        expect(page.locator("#genStatus")).to_contain_text("2 new test cases")
        table = page.locator("#tcTable")
        expect(table).to_contain_text("TC-QPL-2-1")
        expect(table).to_contain_text("TC-QPL-2-2")
        page.get_by_role("checkbox", name="Select TC-QPL-2-1").check()
        expect(page.locator("#tcRun")).to_have_text("Run selected (1)")
        page.locator("#tcRun").click()
        expect(page.locator("#view-execution")).to_be_visible()
        expect(page.locator("#exSelCount")).to_have_text("1")
        page.fill("#exUrl", "https://www.saucedemo.com/")
        page.fill("#exUser", "standard_user")
        page.fill("#exPass", "secret_sauce")
        page.locator("#exAuth").check()
        page.locator("#exStart").click()
        expect(page.locator("#xcStatus")).to_contain_text("Running 1 test case")
        expect(page.locator("#exPass")).to_have_value("")  # (sent once, not kept in the page)
        assert [t["tc"] for t in launched["req"].requirement_tests] == ["TC-QPL-2-1"]
        assert launched["req"].requirements_only and launched["req"].test_password == "secret_sauce"
        expect(page.locator("#exDetail")).to_contain_text("running")
        assert "secret_sauce" not in page.content()
        # the run finishes: its real result file is read, nothing is assumed
        run = tmp_path / "runs" / "ui_run"
        run.mkdir(parents=True)
        (run / "test_cases.json").write_text(json.dumps([{
            "requirement_test": "TC-QPL-2-1", "execution_status": "Passed", "check_count": 3,
            "actual_result": "the dashboard opened", "evidence": ["screenshots/ok.png"]}]))
        monkeypatch.setattr(server, "_plain_run_dir", lambda name: run)
        server.jobs[5151].update(status="done", run="ui_run")
        expect(page.locator("#exDetail")).to_contain_text("Passed", timeout=10000)
        expect(page.locator("#exDetail")).to_contain_text("the dashboard opened")
        page.goto(studio.url + "/requirements#traceability")
        tr = page.locator("#trTable")
        expect(tr).to_contain_text("TC-QPL-2-1")
        expect(tr).to_contain_text("Passed")
        # the requirement's drawer: its test cases, results and trace
        page.goto(studio.url + "/requirements#analysis")
        page.get_by_role("button", name="QPL-2 — User Login Functionality").click()
        drawer = page.locator("#detail")
        page.get_by_role("tab", name="Test Cases").click()
        expect(drawer).to_contain_text("TC-QPL-2-1")
        expect(drawer).to_contain_text("TC-QPL-2-2")
        page.get_by_role("tab", name="Execution Results").click()
        expect(drawer).to_contain_text("the dashboard opened")
        page.get_by_role("tab", name="Traceability").click()
        expect(drawer).to_contain_text("TC-QPL-2-1")
        expect(drawer).not_to_contain_text("Upcoming")
        assert not errors, errors
    finally:
        server.jobs.pop(5151, None)
        ctx.close()


def test_defects_and_write_back_in_chromium_never_send_while_off(browser, studio, monkeypatch, tmp_path):
    """Phase 5 in the browser: a failed requirement test -> a defect -> a proposed Jira bug and a results comment,
    each with the exact request previewed, approved by the reviewer - and still NOT sent, because write-back is off."""
    from backend import server
    ex = _studio_with_a_failed_run(studio, monkeypatch, tmp_path)
    ctx, page, errors = open_page(browser, studio)
    try:
        page.goto(studio.url + "/requirements#execution")
        page.get_by_role("button", name=ex["id"]).click()
        page.get_by_role("button", name="Propose these results to Jira").click()
        expect(page.locator("#view-writeback")).to_be_visible()
        writes = page.locator("#wbWrites")
        expect(writes).to_contain_text("comment on QPL-2")
        expect(writes).to_contain_text("TC-QPL-2-1")
        table = page.locator("#dfTable")
        expect(table).to_contain_text("TC-QPL-2-1")
        expect(table).to_contain_text("likely defect")
        expect(table).to_contain_text("the dashboard never opened")
        table.get_by_role("button", name="Propose Jira bug").click()
        expect(writes).to_contain_text("new issue in QPL")
        bug = writes.locator("article", has_text="new issue in QPL")
        bug.get_by_text("Exact request that would be sent").click()
        expect(bug).to_contain_text('"issuelinks"')
        bug.get_by_role("button", name="Approve").click()
        bug = writes.locator("article", has_text="new issue in QPL")
        expect(bug).to_contain_text("approved by local-user")
        send = bug.get_by_role("button", name="Send to Jira")
        expect(send).to_be_disabled()
        expect(bug).to_contain_text("the server owner has not allowed write-back")
        expect(page.locator("#wbState input[name=enabled]")).to_be_disabled()
        page.locator("#wbState input[name=wtoken]").fill("not-a-real-token-but-long-enough-1234567890")
        page.get_by_role("button", name="Store write token").click()
        expect(page.locator("#wbState")).to_contain_text("stored (studio)")
        assert "not-a-real-token-but-long-enough" not in page.content()
        writes_to_jira = [r for r in studio.mock.requests if r["method"] == "POST" and (
            r["path"] == "/rest/api/3/issue" or r["path"].endswith("/comment"))]
        assert writes_to_jira == []  # (nothing was written to Jira)
        assert not errors, errors
    finally:
        server.jobs.pop(5252, None)
        ctx.close()


def _studio_with_a_failed_run(studio, monkeypatch, tmp_path) -> dict:
    """QPL-2 imported, analysed, two ideas accepted, test cases generated, one execution whose run failed TC-QPL-2-1
    (the run launcher is replaced; its result file is real JSON read by the bridge). Returns the execution."""
    import json
    from urllib.parse import quote

    import httpx

    from backend import server
    monkeypatch.delenv("QPILOT_JIRA_WRITEBACK", raising=False)
    h = {"X-Agentic-QA": "1"}
    with httpx.Client(base_url=studio.url, headers=h, timeout=30) as c:
        c.post("/api/requirements/connections", json={
            "id": "jira-main", "product": "jira", "site_url": "https://aimaniforall1234-1795449805793.atlassian.net",
            "email": EMAIL})
        c.put("/api/requirements/connections/jira-main/token", json={"token": TOKEN})
        job = c.post("/api/requirements/connections/jira-main/imports", json={"mode": "items", "keys": "QPL-2"}).json()
        rapi.JOBS.wait(job["id"])
        analysis = c.post("/api/requirements/items/jira-main/QPL-2/analyze", json={}).json()["analysis"]
        for s in analysis["suggestions"][:2]:
            c.post(f"/api/requirements/items/jira-main/QPL-2/suggestions/{quote(s['id'], safe='')}/review",
                   json={"answer": "yes"})
        c.post("/api/requirements/items/jira-main/QPL-2/test-cases")
        monkeypatch.setattr(server, "_launch_run", lambda req, caller: (
            server.jobs.__setitem__(5252, {"id": 5252, "status": "running", "run": ""}) or {"id": 5252}))
        ex = c.post("/api/requirements/executions", json={
            "strategy": "requirements", "scope": {"requirements": ["QPL-2"]},
            "target": {"url": "https://www.saucedemo.com/", "authorized": True}}).json()["execution"]
        run = tmp_path / "runs" / "ui_fail"
        run.mkdir(parents=True)
        (run / "test_cases.json").write_text(json.dumps([{
            "requirement_test": "TC-QPL-2-1", "execution_status": "Failed", "actual_result": "the dashboard never opened",
            "failure_category": "Application defect (potential website bug)", "confidence": "high"}]))
        monkeypatch.setattr(server, "_plain_run_dir", lambda name: run)
        server.jobs[5252].update(status="done", run="ui_fail")
        assert c.get(f"/api/requirements/executions/{ex['id']}").json()["execution"]["status"] == "finished"
    return ex


def test_filled_phase_4_and_5_screens_fit_a_phone_and_every_control_is_named(browser, studio, monkeypatch, tmp_path):
    import os
    _studio_with_a_failed_run(studio, monkeypatch, tmp_path)
    shots = os.environ.get("QPILOT_UI_SCREENSHOTS")
    ctx, page, errors = open_page(browser, studio, {"width": 390, "height": 844})
    try:
        for view in ("builder", "execution", "agents", "evidence", "traceability", "coverage", "writeback"):
            page.goto(studio.url + f"/requirements#{view}")
            page.wait_for_load_state("networkidle")
            if view == "execution":
                page.locator("#exList button.rq-open").first.click()
                expect(page.locator("#exDetail")).to_contain_text("Failed")
            if view == "writeback":
                expect(page.locator("#dfTable")).to_contain_text("TC-QPL-2-1")
                page.get_by_role("button", name="Propose Jira bug").click()
                expect(page.locator("#wbWrites")).to_contain_text("new issue in QPL")
            wide = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert wide <= 1, f"{view} scrolls sideways by {wide}px"
            unnamed = page.evaluate("""() => [...document.querySelectorAll('main input, main select, main textarea, main button')]
                .filter(el => el.offsetParent !== null)
                .filter(el => !(el.labels && el.labels.length) && !el.getAttribute('aria-label') && !el.textContent.trim()
                              && !el.getAttribute('aria-labelledby') && !el.title)
                .map(el => el.outerHTML.slice(0, 80))""")
            assert unnamed == [], f"{view}: {unnamed}"
            if shots:
                Path(shots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(shots) / f"phone_{view}.png"), full_page=True)
        assert not errors, errors
    finally:
        ctx.close()


def test_an_older_cached_page_with_the_new_script_says_reload_instead_of_going_blank(browser, studio):
    """Seen on a Mac: the browser kept the old /requirements page (older menu) and loaded the new script -> blank
    main area. The script now detects the older page and tells the person to reload."""
    import subprocess
    old = subprocess.run(["git", "show", "581bb51:frontend/requirements.html"], check=False, capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parent.parent)
    if old.returncode:
        pytest.skip("the older page is not in this checkout's history")
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        page.route(studio.url + "/requirements", lambda route: route.fulfill(status=200, content_type="text/html",
                                                                             body=old.stdout))
        page.goto(studio.url + "/requirements#overview")
        expect(page.get_by_role("alert").filter(has_text="older copy")).to_contain_text("Cmd+Shift+R")
    finally:
        ctx.close()
