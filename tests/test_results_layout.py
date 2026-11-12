"""Report evidence and responsive result navigation. All browser traffic is intercepted."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from backend import server

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("mode,with_cases,with_excel", [
    ("discovery", False, False), ("full", False, False),
    ("full", True, False), ("full", True, True),
])
def test_case_artifacts_are_reported_independently(tmp_path, monkeypatch, mode, with_cases, with_excel):
    run = tmp_path / "sample"
    run.mkdir()
    monkeypatch.setattr(server, "RUNS", tmp_path)
    (run / "summary.json").write_text(json.dumps({"mode": mode, "setup_error": "Design unavailable"}))
    if with_cases:
        (run / "test_cases.json").write_text(json.dumps([{"id": "one", "title": "Login"}]))
    if with_excel:
        (run / "test_cases.xlsx").write_bytes(b"artifact")
    with TestClient(server.app, base_url="http://127.0.0.1:8000") as client:
        data = client.get("/api/cases/sample").json()
        assert data["total"] == int(with_cases)
        assert data["available"] is with_cases
        assert data["excel_available"] is with_excel
        assert data["discovery_only"] is (mode == "discovery")
        assert data["complete"] is True
        assert data["empty_reason"] == "Design unavailable"
        report = client.get("/api/report/sample").json()
        assert report["cases_available"] is with_cases
        assert bool(report["excel"]) is with_excel


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def studio(browser, scenario="discovery", viewport=None):
    context = browser.new_context(viewport=viewport or {"width": 1440, "height": 900})
    page = context.new_page()
    errors, calls = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    summary = {"mode": "discovery" if scenario == "discovery" else "full",
               "discovery_only": scenario == "discovery", "pages": 12,
               "verdict": "Insufficient Evidence", "test_cases": 0, "reasons": []}
    report = {"summary": summary, "pages": [], "cases_available": scenario in ("cases", "excel"),
              "excel": "/runs/sample/test_cases.xlsx" if scenario == "excel" else None,
              "components_count": 600, "components_report": "/runs/sample/components.html",
              "report_html": "/runs/sample/report.html", "crawl": {"visited": 12, "not_visited_count": 0},
              "fixes": [], "failures": [], "videos": []}
    cases = {"total": 0, "cases": [], "complete": True, "excel_available": scenario == "excel",
             "empty_reason": "Design unavailable"}
    if scenario in ("cases", "excel"):
        cases.update(total=35, cases=[{"id": str(i), "n": i, "title": "Check navigation " + str(i),
                     "priority": "medium", "status": "Not run"} for i in range(1, 36)],
                     done=0, passed=0, failed=0, links={})

    def respond(route):
        request = route.request
        path = urlsplit(request.url).path
        calls.append(path)
        if request.method != "GET":
            return route.fulfill(status=403, json={"detail": "No run may start in a layout test"})
        if path == "/":
            return route.fulfill(content_type="text/html", body=(ROOT / "frontend/chat.html").read_text(encoding="utf-8"))
        if path.startswith("/static/"):
            name = Path(path).name
            return route.fulfill(content_type="text/css" if name.endswith(".css") else "text/javascript",
                                 body=(ROOT / "frontend" / name).read_text(encoding="utf-8"))
        data = {}
        if path == "/api/settings/privacy":
            data = {"mode": "local", "cloud_consent": False, "allow_mcp": False,
                    "allowed_providers": ["none", "ollama"]}
        elif path == "/api/history":
            data = [{"run": "sample", "url": "https://example.test", "date": "Today", "verdict": "Insufficient Evidence"}]
        elif path == "/api/schedules":
            data = []
        elif path == "/api/runs/latest":
            data = None
        elif path == "/api/report/sample":
            if scenario == "report-error":
                return route.fulfill(status=500, json={"detail": "unavailable"})
            data = report
        elif path == "/api/pages/sample":
            data = {"pages": []}
        elif path == "/api/cases/sample":
            if scenario == "case-error":
                return route.fulfill(status=500, json={"detail": "unavailable"})
            data = {"detail": "bad payload"} if scenario == "case-invalid" else cases
        elif path == "/api/coverage/sample":
            data = None
        elif path == "/api/mcp/connection":
            data = {"server_online": False, "assistant_active": False}
        elif path == "/api/providers":
            data = {"providers": [], "default": "none"}
        elif path.endswith("/repo-fix"):
            data = {"fixes_with_code": 0}
        else:
            return route.fulfill(status=404, json={"detail": "Unstubbed " + path})
        route.fulfill(json=data)

    page.route("**/*", respond)
    page.goto("http://127.0.0.1:8299/", wait_until="networkidle")
    page.locator("#recent .open").wait_for()
    return context, page, errors, calls


@pytest.mark.parametrize("width,height", [(1440, 900), (1137, 687), (1024, 529), (390, 844)])
def test_discovery_uses_the_available_workspace(browser, width, height, tmp_path):
    context, page, errors, calls = studio(browser, viewport={"width": width, "height": height})
    try:
        if page.locator("#menuBtn").is_visible():
            page.locator("#menuBtn").click()
        page.locator("#recent .open").click()
        expect(page.locator(".exploration-result")).to_be_visible()
        assert page.locator("body").get_attribute("data-setup-state") == "results"
        expect(page.locator(".workflow-choice")).to_be_hidden()
        expect(page.locator("#composer")).to_be_hidden()
        expect(page.locator("#resultsNewBtn")).to_be_visible()
        text = page.locator("#thread").inner_text()
        assert "Functional tests were not generated or run." in text
        assert "600" in text
        assert "0 test cases" not in text and "saved them to Excel" not in text
        assert "/api/cases/sample" not in calls
        assert page.locator("#todoList li").count() == 3
        assert page.locator("#todoList li.done").count() == 3
        dimensions = page.evaluate("""() => {
          const t=document.querySelector('#thread'),r=t.getBoundingClientRect();
          return {height:r.height,bottom:r.bottom,viewport:innerHeight,
                  width:document.documentElement.scrollWidth,viewportWidth:innerWidth};
        }""")
        assert dimensions["height"] > height * .65, dimensions
        assert dimensions["bottom"] <= height + 1, dimensions
        assert dimensions["width"] <= width + 1, dimensions
        page.screenshot(path=str(tmp_path / f"results-{width}x{height}.png"))
        page.locator("#resultsNewBtn").click()
        expect(page.locator("#composer")).to_be_visible()
        assert page.locator("body").get_attribute("data-setup-state") == "idle"
        expect(page.locator(".exploration-result")).to_have_count(0)
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize("scenario", ["empty", "cases", "excel", "case-error", "case-invalid", "report-error"])
def test_results_only_offer_existing_artifacts(browser, scenario):
    context, page, errors, calls = studio(browser, scenario)
    try:
        if page.locator("#menuBtn").is_visible():
            page.locator("#menuBtn").click()
        page.locator("#recent .open").click()
        if scenario == "report-error":
            expect(page.locator("#thread [role=alert]")).to_contain_text("Could not load this report")
        else:
            expect(page.locator("#thread")).to_contain_text("final report")
            text = page.locator("#thread").inner_text()
            assert "0 test cases" not in text
            assert "Running the tests now" not in text
            assert "Nothing - no problems found" not in text
            if scenario == "empty":
                expect(page.locator(".result-empty")).to_contain_text("No test cases were generated")
                expect(page.locator(".result-empty")).to_contain_text("Design unavailable")
                assert page.locator("#thread table").count() == 0
            if scenario in ("case-error", "case-invalid"):
                expect(page.locator("#thread [role=alert]")).to_contain_text("Could not load test cases")
            excel_links = page.locator('#thread a[href="/api/excel/sample/download"]')
            assert (excel_links.count() > 0) is (scenario == "excel")
            assert ("saved them to Excel" in text) is (scenario == "excel")
            if scenario in ("cases", "excel"):
                expect(page.locator("#thread table")).to_be_visible()
                page.locator("#thread").evaluate("(e) => e.scrollTop=e.scrollHeight")
                last = page.locator("#thread > .msg").last
                assert last.bounding_box()["height"] > 100
        assert not errors
    finally:
        context.close()


def test_leaving_a_pending_report_cannot_repopulate_new_test(browser):
    context, page, errors, calls = studio(browser)
    held = []
    page.route("**/api/report/sample", lambda route: held.append(route))
    try:
        if page.locator("#menuBtn").is_visible():
            page.locator("#menuBtn").click()
        page.locator("#recent .open").click()
        page.wait_for_function("document.body.dataset.setupState === 'results'")
        page.wait_for_timeout(100)
        assert held
        page.locator("#resultsNewBtn").click()
        held.pop().fulfill(json={"summary": {"discovery_only": True, "pages": 12}})
        page.wait_for_timeout(150)
        assert page.locator("body").get_attribute("data-setup-state") == "idle"
        expect(page.locator(".exploration-result")).to_have_count(0)
        expect(page.locator("#composer")).to_be_visible()
        assert not errors
    finally:
        context.close()


def running_studio(browser, viewport=None, engine="android"):
    """Exercise actual polling UI without starting a device, website test or AI job."""
    context, page, errors, calls = studio(browser, viewport=viewport)
    state = {"revision": 0, "polls": 0, "lines": ["Initial execution log"], "design": False}
    job = {"id": "sample", "run": "sample", "target_type": engine, "status": "running",
           "source": "Android demo application", "current": "execution"}

    def status(route):
        state["polls"] += 1
        stages = {"execution": "running", **({"test_design": "done"} if state["design"] else {})}
        route.fulfill(json={**job, "stages": stages,
                            "status": state.get("status", "running"),
                            "report_ready": state.get("status") == "done",
                            "lines": state["lines"], "next": state["revision"] + 1})
        state["lines"] = []

    def cases(route):
        rows = [{"id": f"case-{i}", "n": i + 1, "priority": "medium",
                 "title": f"Check navigation {i}", "page": "Demo screen",
                 "status": "Passed", "steps_done": [{"ok": True, "text": f"Read value for case {i}"}]}
                for i in range(35)]
        rows[0]["steps_done"] *= state["revision"] + 1
        route.fulfill(json={"total": 35, "excel_available": state["design"],
                            "done": state["revision"], "passed": state["revision"],
                            "failed": 0, "cases": rows, "links": {}})

    page.route("**/api/runs/latest", lambda route: route.fulfill(json=job))
    page.route("**/api/runs/sample?*", status)
    page.route("**/api/cases/sample", cases)
    page.reload(wait_until="networkidle")
    expect(page.locator("#m-exec .case")).to_have_count(35)
    return context, page, errors, state


def next_live_update(page, state):
    polls = state["polls"]
    # An in-flight case refresh can render a new revision before the next
    # status poll. Wait for that poll explicitly before checking its count.
    with page.expect_response(lambda response: "/api/runs/sample?" in response.url and state["polls"] > polls):
        state["revision"] += 1
        state["lines"] = [f"New execution evidence {state['revision']}"]
    page.wait_for_function("r => document.querySelector('#m-exec').textContent.includes(r)",
                           arg=f"{state['revision']}/35 test cases")
    assert state["polls"] > polls


@pytest.mark.parametrize("width,height", [(1440, 900), (1024, 529), (390, 844)])
@pytest.mark.parametrize("engine", ["android", "web"])
def test_running_results_have_one_vertical_scroll_surface(browser, width, height, engine):
    context, page, errors, state = running_studio(browser, {"width": width, "height": height}, engine)
    try:
        thread = page.locator("#thread")
        first = page.locator("#m-exec .case").first
        first.scroll_into_view_if_needed()
        metrics = page.locator("#m-exec .cases").evaluate(
            "e => ({content:e.scrollHeight, visible:e.clientHeight})")
        assert metrics["content"] <= metrics["visible"] + 1, metrics
        before = thread.evaluate("e => e.scrollTop")
        first.hover()
        page.mouse.wheel(0, 500)
        page.wait_for_function("top => document.querySelector('#thread').scrollTop > top + 100", arg=before)
        page.locator("#m-exec .case").last.scroll_into_view_if_needed()
        expect(page.locator("#stopBtn")).to_be_in_viewport()
        bounds = thread.bounding_box()
        assert bounds["height"] > height * .65
        assert bounds["y"] + bounds["height"] <= height + 1
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
    finally:
        context.close()


def test_live_refresh_keeps_open_steps_and_the_case_being_read(browser):
    context, page, errors, state = running_studio(browser)
    try:
        first_details = page.locator("#m-exec .case").first.locator("details")
        first_details.locator("summary").click()
        details = page.locator("#m-exec .case").nth(18).locator("details")
        details.locator("summary").click()
        target = page.locator("#m-exec .case").nth(18)
        target.evaluate("e => e.scrollIntoView({block:'start'})")
        page.wait_for_timeout(100)
        before = target.bounding_box()["y"]
        next_live_update(page, state)
        assert first_details.get_attribute("open") is not None
        assert details.get_attribute("open") is not None
        assert abs(target.bounding_box()["y"] - before) < 3
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize("input_method", ["wheel", "keyboard"])
def test_scrolling_up_near_the_bottom_pauses_live_following(browser, input_method):
    context, page, errors, state = running_studio(browser)
    try:
        thread = page.locator("#thread")
        thread.evaluate("e => {e.style.scrollBehavior='auto'; e.scrollTop=e.scrollHeight}")
        page.wait_for_timeout(100)
        box = thread.bounding_box()
        page.mouse.move(box["x"] + 10, box["y"] + box["height"] - 30)
        if input_method == "wheel":
            page.mouse.wheel(0, -65)
        else:
            thread.focus()
            page.keyboard.press("ArrowUp")
        page.wait_for_timeout(150)
        before = thread.evaluate("e => e.scrollTop")
        next_live_update(page, state)
        assert abs(thread.evaluate("e => e.scrollTop") - before) < 3
        expect(page.locator("#jumpBtn")).to_be_visible()
        page.locator("#jumpBtn").click()
        assert thread.evaluate("e => e.scrollHeight-e.clientHeight-e.scrollTop") < 3
        next_live_update(page, state)
        assert thread.evaluate("e => e.scrollHeight-e.clientHeight-e.scrollTop") < 3
        assert not errors
    finally:
        context.close()


def test_excel_can_be_scrolled_and_filtered_while_execution_updates(browser):
    context, page, errors, state = running_studio(browser, {"width": 1024, "height": 529})
    workbook = {"name": "test_cases.xlsx", "sheets": [{"name": "Test Cases",
                "headers": ["Test case", "Execution Status"],
                "rows": [[f"Navigation {i}", "Passed"] for i in range(80)]}]}
    page.route("**/api/excel/sample", lambda route: route.fulfill(json=workbook))
    try:
        state["design"] = True
        page.locator(".view-xl").click()
        expect(page.locator("#excelModal")).to_be_visible()
        wrap = page.locator(".sheet-wrap")
        wrap.hover()
        page.mouse.wheel(0, 400)
        page.wait_for_function("document.querySelector('.sheet-wrap').scrollTop > 100")
        before = wrap.evaluate("e => e.scrollTop")
        next_live_update(page, state)
        assert abs(wrap.evaluate("e => e.scrollTop") - before) < 3
        page.locator("#excelSearch").fill("Navigation 79")
        expect(page.locator("#sheet tbody tr")).to_have_count(1)
        expect(page.locator("#sheet")).to_contain_text("Navigation 79")
        page.locator("#excelClose").click()
        expect(page.locator("#stopBtn")).to_be_in_viewport()
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize("width,height", [(1137, 687), (1024, 529), (390, 600)])
def test_android_configuration_has_enough_space_and_scrolls_to_start(browser, width, height):
    context, page, errors, calls = studio(browser, viewport={"width": width, "height": height})
    page.route("**/api/android/environment?*", lambda route: route.fulfill(json={
        "ok": True, "devices": [{"device_id": "fixture", "status": "device"}]}))
    try:
        page.locator("#mobileModeBtn").click()
        form = page.locator("#mobileForm")
        expect(form).to_be_visible()
        expect(page.locator("#todoList li").first).to_contain_text("Connect to Android device")
        assert form.bounding_box()["height"] >= height * .45
        form.hover()
        page.mouse.wheel(0, 2500)
        page.wait_for_function("document.querySelector('#mobileForm').scrollTop > 100")
        expect(page.locator("#androidStart")).to_be_in_viewport()
        expect(page.locator(".chat-top")).to_be_in_viewport()
        page.locator("#mobileCancel").click()
        expect(page.locator("#composer")).to_be_visible()
        expect(page.locator("#todoList li").first).to_contain_text("Open the website")
        assert not errors
        assert "/api/mobile/runs" not in calls
    finally:
        context.close()


def test_short_navigation_sidebar_scrolls_to_its_footer(browser):
    context, page, errors, calls = studio(browser, viewport={"width": 1440, "height": 480})
    try:
        sidebar = page.locator(".app > .side")
        sidebar.hover()
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(150)
        expect(page.locator(".side-footer")).to_be_in_viewport()
        assert not errors
    finally:
        context.close()


def test_unavailable_device_explains_disabled_start_at_the_bottom_of_setup(browser):
    context, page, errors, calls = studio(browser, viewport={"width": 1024, "height": 529})
    page.route("**/api/android/environment?*", lambda route: route.fulfill(json={
        "ok": False, "devices": [], "errors": ["No Android device is connected."]}))
    try:
        page.locator("#mobileModeBtn").click()
        expect(page.locator("#androidRunNote")).to_contain_text("No Android device is connected")
        page.locator("#mobileForm").hover()
        page.mouse.wheel(0, 2500)
        expect(page.locator("#androidRunNote")).to_be_in_viewport()
        expect(page.locator("#androidStart")).to_be_disabled()
        assert not errors
    finally:
        context.close()


def test_execution_plan_can_be_scrolled_without_moving_results(browser):
    context, page, errors, state = running_studio(browser, {"width": 1137, "height": 529})
    try:
        thread = page.locator("#thread")
        top = thread.evaluate("e => e.scrollTop")
        plan = page.locator("#todo")
        plan.hover()
        page.mouse.wheel(0, 1000)
        page.wait_for_function("document.querySelector('#todo').scrollTop > 50")
        expect(page.locator("#costCalls")).to_be_in_viewport()
        assert abs(thread.evaluate("e => e.scrollTop") - top) < 3
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize("verdict", ["Insufficient Evidence", "Not Ready", "Ready with Risks", "Ready"])
def test_completed_android_header_shows_the_quality_verdict(browser, verdict):
    context, page, errors, state = running_studio(browser)
    page.route("**/api/report/sample", lambda route: route.fulfill(json={"summary": {
        "verdict": verdict, "reasons": ["Scope and outcome must be reviewed"]}}))
    try:
        state["status"] = "done"
        expect(page.locator("#statusPill")).to_have_text(verdict)
        if verdict != "Ready":
            assert "ok" not in (page.locator("#statusPill").get_attribute("class") or "").split()
        assert not errors
    finally:
        context.close()
