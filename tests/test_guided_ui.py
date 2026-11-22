"""Your own tests need an AI: with 'Rules only' the studio does not start silently - it asks to choose an AI or
confirm that the instructions are listed as not automated. The focus option is sent with the run."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def studio():
    started = []

    def route(request):
        path = urlsplit(request.request.url).path
        if path.startswith("/api/"):
            if path == "/api/runs" and request.request.method == "POST":
                started.append(request.request.post_data_json)
                data = {"id": 1, "status": "running"}
            elif path == "/api/check":
                data = {"kind": "website", "ok": True, "url": "https://login-first.test/", "final_url":
                        "https://login-first.test/auth/login", "status": 200, "ms": 5, "login": False,
                        "has_test_account": False, "title": "Login", "my_tests": []}
            elif path == "/api/settings/privacy":
                data = {"mode": "local", "allowed_providers": ["ollama", "none"], "allow_mcp": False}
            elif path in ("/api/history", "/api/schedules"):
                data = []
            elif path == "/api/providers":
                data = {"default": "none", "env_provider": "none", "providers": [
                    {"id": "none", "name": "Rules only", "models": [], "ready": True}]}
            else:
                data = {}
            request.fulfill(content_type="application/json", body=json.dumps(data))
        elif path.startswith("/static/"):
            file = ROOT / "frontend" / path.removeprefix("/static/")
            request.fulfill(content_type="text/css" if file.suffix == ".css" else "text/javascript",
                            body=file.read_text(encoding="utf-8"))
        else:
            request.fulfill(content_type="text/html", body=(ROOT / "frontend" / "chat.html").read_text(encoding="utf-8"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.route("http://qpilot.fixture/**", route)
        page.route(re.compile(r"https://.*"), lambda r: r.abort())
        page.goto("http://qpilot.fixture/")
        page.fill("#msg", "https://login-first.test/")
        page.click("#sendBtn")
        page.wait_for_selector("#aiAccountMode")
        yield page, started
        browser.close()


def test_instructions_with_rules_only_are_refused_until_confirmed(studio):
    page, started = studio
    if not page.locator("#myTests").is_visible():
        page.locator("summary", has_text="Your own tests").click()
    page.fill("#myTests", "Navigate to PIM and test employee search")
    page.check("#myFocus")
    page.get_by_text("Rules only").first.click()
    page.check("#aiAuth")
    page.click("#aiStart")
    page.wait_for_timeout(300)
    assert "need an AI" in page.locator("#aiNote").inner_text()
    assert started == []
    page.check("#myNoAiOk")
    page.click("#aiStart")
    page.wait_for_timeout(500)
    assert len(started) == 1
    assert started[0]["my_tests"] == "Navigate to PIM and test employee search"
    assert started[0]["objective_focus"] is True
