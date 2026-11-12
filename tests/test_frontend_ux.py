"""Phase 7 frontend UX hardening: empty/error states, a11y basics, HTML escaping.

Characterization and regression only — no live device, AI, or website run.
"""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.test_results_layout import browser as shared_browser, studio

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


@pytest.fixture(scope="module")
def browser():
    yield from shared_browser.__wrapped__()


def test_studio_markup_keeps_loading_copy_and_basic_aria_hooks():
    html = (FRONTEND / "chat.html").read_text(encoding="utf-8")
    assert "Loading privacy settings…" in html
    assert "Checking connection…" in html
    assert 'id="statusPill" role="status" aria-live="polite"' in html
    assert 'aria-label="Jump to the latest progress"' in html
    assert 'aria-describedby="composer-hint"' in html
    assert 'id="todoList" aria-live="polite"' in html
    assert "Loading recent runs…" in html and "Loading schedules…" in html
    assert "Loading privacy settings?" not in html
    assert "Checking connection?" not in html


def test_chat_js_escapes_history_and_surfaces_load_failures():
    script = (FRONTEND / "chat.js").read_text(encoding="utf-8")
    assert 'const esc = (s) => String(s ?? "").replace(/[&<>"\']/g' in script
    assert "Could not load recent runs." in script
    assert "Could not load schedules." in script
    assert "No tests yet. Configure a website or Android app" in script
    assert "loadSchedules();" in script.split("async function loadHistory")[1].split("async function loadSchedules")[0]
    # Untrusted history fields stay escaped in the HTML sink.
    assert "${esc(r.run)}" in script and "${esc(r.date)}" in script and "${esc(r.verdict)}" in script
    assert "${esc(label)}" in script
    assert "Preparing configuration?" not in (FRONTEND / "workflow.js").read_text(encoding="utf-8")


def test_thorough_exploration_preset_and_coverage_reminder_are_wired():
    """Standard/Thorough intensity must drive crawl options and surface missed coverage."""
    script = (FRONTEND / "chat.js").read_text(encoding="utf-8")
    css = (FRONTEND / "chat.css").read_text(encoding="utf-8")
    assert 'id="aiIntensity"' in script
    assert 'value="thorough"' in script and 'value="standard"' in script
    assert 'value="thorough" selected' in script  # Thorough is the Studio default
    assert "function applyExplorationIntensity()" in script
    assert "function focusThoroughSetup()" in script
    assert "function coverageReminderHtml(" in script
    assert "HARD_PAGE_CAP" in script and "Unvisited pages remain listed" in script
    assert "≥60 min crawl" in script or "60 min crawl" in script
    assert 'explore_repeated_controls: thorough || fullCrawl' in script
    assert "thorough: !!thorough" in script
    assert "thorough ? 80" in script or "thorough ? 80 :" in script
    assert 'crawl_scope: thorough ? "site"' in script
    assert "coverageReminderHtml(s, crawl)" in script
    assert "coverageReminderHtml(s, d.crawl || s.crawl)" in script
    assert "Coverage reminder:" in script
    assert "Run Thorough again" in script and "thorough-again" in script
    assert "Observed/scripted controls are not the same as business-verified checks." in script
    assert ".warn.coverage-reminder" in css
    assert ".coverage-reminder-actions" in css


def test_qa_lab_empty_and_progress_copy_without_redesign():
    page = (FRONTEND / "qa-lab.html").read_text(encoding="utf-8")
    script = (FRONTEND / "qa-lab.js").read_text(encoding="utf-8")
    assert 'aria-label="Accuracy lab navigation"' in page
    assert 'id="status" role="status" aria-live="polite"' in page
    assert "Loading completed runs…" in page
    assert "No completed runs available yet" in script
    assert "Building evidence report…" in script
    assert "option.textContent" in script  # run labels are not injected as HTML
    assert "innerHTML" not in script


def test_contract_builder_keeps_escape_helper_and_validation_feedback():
    script = (FRONTEND / "contract-builder.js").read_text(encoding="utf-8")
    assert 'const esc = value => String(value ?? "").replace(/[&<>"\']/g' in script
    assert 'aria-label="Close test flow builder"' in script
    assert "Validating the flow…" in script
    assert "${esc(example.id)}" in script and "${esc(example.name)}" in script
    assert "${esc(flow.id)}" in script and "${esc(flow.title)}" in script


def test_recent_runs_escape_untrusted_labels_and_report_load_errors(browser):
    context, page, errors, calls = studio(browser)
    try:
        page.route("**/api/history", lambda route: route.fulfill(json=[{
            "run": "evil-run",
            "url": "https://example.test/<img src=x onerror=alert(1)>",
            "date": "Today",
            "verdict": "Ready</b><script>window.__xss=1</script>",
        }]))
        page.reload(wait_until="networkidle")
        open_btn = page.locator("#recent .open")
        expect(open_btn).to_be_visible()
        assert page.locator("#recent").inner_html().count("<img") == 0
        assert page.locator("#recent").inner_html().count("<script") == 0
        assert page.evaluate("window.__xss") is None
        expect(open_btn.locator(".r-url")).to_contain_text("<img src=x onerror=alert(1)>")
        expect(open_btn.locator(".r-meta")).to_contain_text("Ready</b><script>window.__xss=1</script>")
        assert open_btn.get_attribute("aria-label").startswith("Open run ")
        assert not errors
    finally:
        context.close()


def test_history_and_schedule_failures_show_clear_empty_states(browser):
    context, page, errors, calls = studio(browser)

    def fail_history(route):
        route.fulfill(status=500, json={"detail": "history offline"})

    def fail_schedules(route):
        route.fulfill(status=500, json={"detail": "schedules offline"})

    page.route("**/api/history", fail_history)
    page.route("**/api/schedules", fail_schedules)
    try:
        page.reload(wait_until="networkidle")
        expect(page.locator("#recent [role=alert]")).to_contain_text("Could not load recent runs")
        expect(page.locator("#schedules [role=alert]")).to_contain_text("Could not load schedules")
        assert page.locator("#recent").get_attribute("aria-busy") is None
        assert page.locator("#schedules").get_attribute("aria-busy") is None
        assert not errors
    finally:
        context.close()


def test_empty_history_still_loads_schedules_and_explains_next_step(browser):
    context, page, errors, calls = studio(browser)
    page.route("**/api/history", lambda route: route.fulfill(json=[]))
    page.route("**/api/schedules", lambda route: route.fulfill(json=[]))
    try:
        page.reload(wait_until="networkidle")
        expect(page.locator("#recent [role=status]")).to_contain_text("No tests yet")
        expect(page.locator("#schedules [role=status]")).to_contain_text("None yet")
        # Empty history used to return before schedules refreshed; both panes must settle.
        assert page.locator("#recent").get_attribute("aria-busy") is None
        assert page.locator("#schedules").get_attribute("aria-busy") is None
        assert page.get_by_label("Jump to the latest progress").count() == 1
        assert page.locator("#msg").get_attribute("aria-describedby") == "composer-hint"
        assert not errors
        assert calls  # studio bootstrap still contacted the stubbed API
    finally:
        context.close()


def test_accuracy_lab_empty_runs_and_build_guard(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def respond(route):
        path = urlsplit(route.request.url).path
        if path == "/qa-lab":
            return route.fulfill(content_type="text/html", body=(FRONTEND / "qa-lab.html").read_text(encoding="utf-8"))
        if path.startswith("/static/"):
            name = Path(path).name
            body = (FRONTEND / name).read_text(encoding="utf-8")
            ctype = "text/css" if name.endswith(".css") else "text/javascript"
            return route.fulfill(content_type=ctype, body=body)
        if path == "/api/history":
            return route.fulfill(json=[])
        return route.fulfill(status=404, json={"detail": "Unstubbed " + path})

    page.route("**/*", respond)
    try:
        page.goto("http://127.0.0.1:8299/qa-lab", wait_until="networkidle")
        expect(page.locator("#status")).to_contain_text("No completed runs available yet")
        expect(page.locator("#runs option").first).to_contain_text("No completed runs yet")
        page.locator("#build").click()
        expect(page.locator("#status[role=alert]")).to_contain_text("Add at least one condition")
        assert page.locator("#report").is_hidden()
        assert not errors
    finally:
        context.close()
