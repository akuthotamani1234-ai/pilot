"""Completed MCP runs remain visible when the user returns from their assistant."""

import pytest
from playwright.sync_api import expect

from tests import test_qpilot_ui

ui = test_qpilot_ui.ui


@pytest.mark.parametrize("status", ["done", "stopped"])
@pytest.mark.parametrize("resume_running", [False, True])
def test_returning_to_studio_loads_completed_mcp_execution_and_report_once(ui, status, resume_running):
    page, requests, errors = ui
    latest = {"value": None}
    report_requests = []
    page.route("**/api/runs/latest", lambda route: route.fulfill(json=latest["value"]))
    page.route("**/api/mcp/connection", lambda route: route.fulfill(json={"server_online": True}))
    page.route("**/api/pages/mcp-short", lambda route: route.fulfill(json={"pages": []}))
    page.route("**/api/cases/mcp-short", lambda route: route.fulfill(json={
        "total": 1, "done": 1, "passed": 1, "failed": 0,
        "cases": [{"id": "cart", "title": "Product and cart agree", "status": "Passed",
                   "steps_done": [{"text": "Verify cart price", "ok": True}]}],
    }))

    def report(route):
        report_requests.append(route.request.url)
        route.fulfill(json={"summary": {"verdict": "Insufficient Evidence", "passed": 1, "test_cases": 1},
                            "report_html": "/runs/mcp-short/report.html"})

    page.route("**/api/report/mcp-short", report)
    completed = {
        "id": 42, "workflow": "mcp", "status": status, "source": "https://example.test/",
        "run": "mcp-short", "target_type": "web", "elapsed": 17, "report_ready": True,
        "stages": {"execution": "done", "report": "done"},
    }
    page.route("**/api/runs/42?**", lambda route: route.fulfill(json=latest["value"]))
    if resume_running:
        latest["value"] = {**completed, "status": "running", "report_ready": False,
                           "stages": {"execution": "running"}}
    page.reload()
    if resume_running:
        expect(page.locator("#stopBtn")).to_be_visible()
    else:
        page.locator("#mcpWorkflowBtn").click()
    # The assistant completes the run while Studio is in another tab.
    latest["value"] = completed
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.locator("#m-report")).to_contain_text("final report")
    expect(page.locator("#m-exec")).to_contain_text("Product and cart agree")
    expect(page.locator("#liveTimeline li")).to_have_count(2)
    expect(page.locator("#stopBtn")).to_be_hidden()
    expect(page.locator("#m-report a.primary")).to_have_attribute("href", "/runs/mcp-short/report.html")
    page.locator("#m-exec details").click()
    expect(page.locator("#m-exec")).to_contain_text("Verify cart price")
    # Returning repeatedly must not attach again or start polling a terminal job.
    with page.expect_response("**/api/runs/latest"):
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(1100)
    assert len(report_requests) == 1
    expect(page.locator("#m-report")).to_have_count(1)
    assert not requests and not errors


def test_standard_completion_does_not_replace_mcp_configuration(ui):
    page, requests, errors = ui
    page.route("**/api/runs/latest", lambda route: route.fulfill(json={
        "id": 43, "workflow": "standard", "status": "done", "run": "other", "report_ready": True,
    }))
    page.locator("#mcpWorkflowBtn").click()
    with page.expect_response("**/api/runs/latest"):
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.locator("#m-report")).to_have_count(0)
    expect(page.locator("#mcpTarget")).to_be_visible()
    assert not requests and not errors
