"""Phase 6: bot protection, CAPTCHA walls, rate limits, access denied, SSO / MFA - recognised (never a defect of the
application, never bypassed), the run paused durably, resumed with an authorized person's session (only the site's own
cookies), or Blocked with the exact blocker when nobody helps."""
import http.server
import json
import threading
import time

import pytest

from backend import access_help as ah


def test_each_kind_of_wall_is_recognised_and_a_normal_page_is_not():
    cf = ah.detect(503, "Just a moment...", "Checking your browser before accessing", "<div id='cf-chl'>Ray ID</div>")
    assert cf["kind"] == "bot_protection" and cf["vendor"] == "Cloudflare" and "allowlist" in cf["help"]
    ak = ah.detect(403, "Access Denied", "You don't have permission to access this. Reference #18.abc",
                   "errors.edgesuite.net")
    assert ak["kind"] == "bot_protection" and ak["vendor"] == "Akamai"
    assert ah.detect(429, "Too Many Requests", "slow down", "")["kind"] == "rate_limited"
    wall = ah.detect(200, "Verify", "Please verify", '<div class="g-recaptcha" data-sitekey="x"></div>')
    assert wall["kind"] == "captcha"
    assert ah.detect(403, "Forbidden", "Access denied for this user", "")["kind"] == "access_denied"
    assert ah.detect(200, "Products", "Our products", "<input><input><button>Buy</button>") is None
    form_with_captcha = "<form>" + "<input>" * 6 + '<div class="g-recaptcha"></div></form>'
    assert ah.detect(200, "Contact", "Write to us", form_with_captcha) is None  # (a form protected by a CAPTCHA)


def test_only_the_applications_own_cookies_are_accepted(tmp_path):
    state = {"cookies": [{"name": "session", "value": "s1", "domain": ".shop.example.com", "path": "/"},
                         {"name": "tracker", "value": "t", "domain": ".ads.example.net", "path": "/"}]}
    assert ah.accept_help(tmp_path, "https://www.shop.example.com/", state) == 1
    saved = json.loads((tmp_path / ah.HELP).read_text())
    assert [c["name"] for c in saved["cookies"]] == ["session"]
    assert ah.accept_help(tmp_path, "https://www.shop.example.com/", {"cookies": [
        {"name": "x", "value": "y", "domain": "evil.example.org"}]}) == 0
    assert ah.accept_help(tmp_path, "https://www.shop.example.com/", None, "a=1; b=2") == 2


def test_a_paused_run_resumes_with_help_or_says_it_is_blocked(tmp_path):
    block = ah.detect(503, "Just a moment...", "", "cloudflare")
    threading.Timer(0.5, lambda: ah.accept_help(tmp_path, "https://shop.example/", None, "cf_clearance=ok")).start()
    helped = ah.wait_for_help(tmp_path, block, "https://shop.example/", wait_s=10)
    assert helped["cookies"][0]["name"] == "cf_clearance"
    assert json.loads((tmp_path / ah.PAUSE).read_text())["state"] == "resumed"
    assert ah.wait_for_help(tmp_path, block, "https://shop.example/", wait_s=0) is None
    assert json.loads((tmp_path / ah.PAUSE).read_text())["state"] == "timed_out"


class _Guarded(http.server.BaseHTTPRequestHandler):
    """A site behind a bot check: the check page unless the visitor has the session a person got past it with."""
    def do_GET(self):
        if "cf_clearance=ok" in (self.headers.get("Cookie") or ""):
            body, status = b"<html><title>Shop</title><body><h1>Products</h1><input><input></body></html>", 200
        else:
            body, status = (b"<html><title>Just a moment...</title><body>Checking your browser before accessing. "
                            b"Ray ID: 123 cloudflare</body></html>"), 503
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_a_real_browser_gets_past_the_check_only_with_the_persons_session(tmp_path):
    from playwright.sync_api import sync_playwright
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Guarded)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_context().new_page()
            resp = page.goto(url)
            block = ah.detect(resp.status, page.title(), page.inner_text("body"), page.content())
            assert block and block["kind"] == "bot_protection"
            threading.Timer(0.5, lambda: ah.accept_help(tmp_path, url, {"cookies": [
                {"name": "cf_clearance", "value": "ok", "domain": "127.0.0.1", "path": "/"}]})).start()
            helped = ah.wait_for_help(tmp_path, block, url, wait_s=10)
            assert ah.apply(page.context, helped) == 1
            resp = page.goto(url)
            assert resp.status == 200 and ah.detect(resp.status, page.title(), page.inner_text("body"),
                                                    page.content()) is None
            assert page.locator("h1").inner_text() == "Products"
            browser.close()
    finally:
        server.shutdown()


@pytest.fixture
def studio(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import server
    run = "web_paused_20261126_000000"
    d = server.RUNS / run
    d.mkdir(parents=True, exist_ok=True)
    server.jobs[9191] = {"id": 9191, "status": "running", "run": run, "source": "https://www.shop.example.com/",
                         "principal_id": ""}
    yield TestClient(server.app, base_url="http://127.0.0.1:8000"), d
    server.jobs.pop(9191, None)
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def test_the_studio_shows_the_pause_and_takes_the_persons_session(studio):
    client, d = studio
    H = {"X-Agentic-QA": "1"}
    assert client.get("/api/runs/9191/pause", headers=H).json() == {"paused": False}
    assert client.post("/api/runs/9191/help", headers=H, json={"cookie_header": "a=1"}).status_code == 409
    ah.pause(d, ah.detect(503, "Just a moment...", "", "cloudflare"), "https://www.shop.example.com/", 60)
    p = client.get("/api/runs/9191/pause", headers=H).json()
    assert p["paused"] and p["kind"] == "bot_protection" and p["vendor"] == "Cloudflare"
    bad = client.post("/api/runs/9191/help", headers=H, json={"storage_state": {"cookies": [
        {"name": "x", "value": "y", "domain": "other.example.org"}]}})
    assert bad.status_code == 400
    ok = client.post("/api/runs/9191/help", headers=H, json={"storage_state": {"cookies": [
        {"name": "session", "value": "s", "domain": ".shop.example.com"}]}})
    assert ok.status_code == 200 and ok.json()["accepted_cookies"] == 1
    assert (d / ah.HELP).is_file()
    time.sleep(0)
