"""Browser-only Qpilot UI review with intercepted APIs; no QA jobs or GitHub calls."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ui():
    (ROOT / ".snapshots" / "qpilot_review").mkdir(parents=True, exist_ok=True)
    requests = []
    plan = {"repo": "fixture/app", "base_branch": "main", "base_commit": "abc123", "proposal_id": "reviewed-1",
            "files": [{"path": "app.py", "diff": "-return False\n+return True"}],
            "applied": [{"title": "Supported fixture issue", "why": "Correct the observed condition"}], "skipped": [],
            "validation": [{"name": "Syntax", "status": "passed"},
                           {"name": "Project regression tests", "status": "unavailable", "detail": "Run CI before merge"}]}
    info = {"repo_url": "", "provider": "none", "has_token": False, "candidates": [
        {"id": "finding-1", "title": "Supported fixture issue", "category": "product_defect", "eligible": True}],
        "preparation": {"status": "idle"}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request):
            path = urlsplit(request.request.url).path
            if path.startswith("/api/"):
                if request.request.method != "GET":
                    requests.append((path, request.request.post_data_json))
                if path == "/api/settings/privacy":
                    data = {"mode": "local", "allowed_providers": ["ollama", "none"], "allow_mcp": False}
                elif path == "/api/history" or path == "/api/schedules":
                    data = []
                elif path == "/api/providers":
                    data = {"default": "none", "env_provider": "none", "providers": [
                        {"id": "none", "name": "Rules only", "models": [], "ready": True}]}
                elif path.endswith("/events"):
                    data = {"cursor": "end", "events": [] if "after=end" in request.request.url else [
                        {"id": "one", "text": "Open the Contact dialog", "test": "Contact form", "worker": "main", "elapsed": 1, "status": "completed"},
                        {"id": "two", "text": "Enter email <img src=x>", "test": "Contact form", "worker": "main", "elapsed": 2, "status": "running"}]}
                elif path.endswith("/repo-fix"):
                    data = info
                elif path.endswith("/repo-fix/prepare"):
                    info["preparation"] = {"status": "ready", "plan": plan}
                    data = {"status": "running"}
                elif path.endswith("/repo-fix/create"):
                    data = {"pr_url": "https://github.com/fixture/app/pull/1"}
                else:
                    data = {}
                request.fulfill(content_type="application/json", body=json.dumps(data))
            elif path.startswith("/static/"):
                file = ROOT / "frontend" / path.removeprefix("/static/")
                content_type = "text/css" if file.suffix == ".css" else "text/javascript"
                request.fulfill(content_type=content_type, body=file.read_text(encoding="utf-8"))
            else:
                request.fulfill(content_type="text/html", body=(ROOT / "frontend" / "chat.html").read_text(encoding="utf-8"))
        page.route("http://qpilot.fixture/**", route)
        page.route(re.compile(r"https://.*"), lambda request: request.abort())
        page.goto("http://qpilot.fixture/")
        yield page, requests, errors
        browser.close()


def test_live_timeline_and_modern_layout(ui):
    page, requests, errors = ui
    snapshots = ROOT / ".snapshots" / "qpilot_review"
    snapshots.mkdir(parents=True, exist_ok=True)
    expect(page).to_have_title("Qpilot")
    expect(page.get_by_role("navigation", name="QA workflow")).to_be_visible()
    page.screenshot(path=str(snapshots / "setup-desktop.png"), full_page=True)
    page.evaluate("""() => {
      document.body.dataset.setupState='running';
      QpilotLive.update({id:7,status:'running',current:'execution',target_type:'web'});
    }""")
    expect(page.locator("#liveTimeline li")).to_have_count(2)
    assert page.locator("#liveTimeline img").count() == 0
    page.evaluate("QpilotLive.update({id:7,status:'running',current:'execution'})")
    expect(page.locator("#liveTimeline li")).to_have_count(2)
    page.screenshot(path=str(snapshots / "live-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    expect(page.locator("#liveCurrent")).to_be_in_viewport()
    expect(page.locator("#side")).to_be_hidden()
    expect(page.locator("#todo")).to_be_hidden()
    page.locator("#menuBtn").click()
    expect(page.locator("#side")).to_be_visible()
    page.locator("#navClose").click()
    expect(page.locator("#side")).to_be_hidden()
    page.screenshot(path=str(snapshots / "live-mobile.png"), full_page=True)
    assert not requests and not errors


def test_repository_requires_review_and_sends_exact_proposal(ui):
    page, requests, errors = ui
    page.evaluate("""async () => {
      document.body.dataset.setupState='results';
      document.getElementById('thread').innerHTML='<section id="repo-test"></section>';
      await QpilotRepo.mount('fixture',document.getElementById('repo-test'));
    }""")
    page.locator("[data-repo]").fill("https://github.com/fixture/app")
    page.get_by_role("button", name="Prepare AI changes").click()
    publish = page.get_by_role("button", name="Create pull request")
    expect(publish).to_be_visible()
    expect(publish).to_be_disabled()
    expect(page.get_by_text("Project regression tests — unavailable")).to_be_visible()
    page.locator("[data-reviewed]").check()
    publish.click()
    expect(page.get_by_role("link", name="Open pull request on GitHub")).to_be_visible()
    assert requests[-1][1]["proposal_id"] == "reviewed-1"
    page.screenshot(path=str(ROOT / ".snapshots" / "qpilot_review" / "repository-preview.png"), full_page=True)
    assert not errors
