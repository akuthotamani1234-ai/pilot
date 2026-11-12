"""The browser goes away in the middle of a run (demowebshop.tricentis.com, Nov 3, 2026,
runs/demowebshop.tricentis.com_20261103_084823): on page 91 the visible Chrome window was closed - by hand, or Chrome
stopped - and the WHOLE run ended in exploring ('BrowserContext.new_page: Target page, context or browser has been
closed'): 90 pages found, no test designed. Now:
  * the crawl opens a new browser with the saved login, visits the page it was on again, and goes on - the closed
    window is never the website's error;
  * a test whose browser was closed gets a new one: the next tests of that browser still run."""
import http.server
import json
import shutil
import threading

from backend.config import settings
from tests.demo_app import PASSWORD, USER, DemoApp


def test_the_crawl_goes_on_in_a_new_browser_with_the_login(tmp_path, monkeypatch, capsys):
    from backend.agents import discovery
    monkeypatch.setattr(settings, "test_username", USER)
    monkeypatch.setattr(settings, "test_password", PASSWORD)
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "max_pages", 30)
    monkeypatch.setenv("TEST_USERNAME", USER)
    monkeypatch.setenv("TEST_PASSWORD", PASSWORD)
    closed = {"at": ""}
    real = discovery.autoscroll

    def a_person_closes_chrome(page):  # (on the first page behind the login: the whole browser goes away)
        if not closed["at"] and page.url.rstrip("/").endswith("/dashboard"):
            closed["at"] = page.url
            page.context.browser.close()
        return real(page)
    monkeypatch.setattr(discovery, "autoscroll", a_person_closes_chrome)
    demo = DemoApp().start()
    try:
        out = discovery.discovery_agent({"url": demo.url, "run_dir": str(tmp_path), "site_key": "demo", "log": []})
    finally:
        demo.stop()
    assert closed["at"], "the browser was never closed - the test proves nothing"
    said = capsys.readouterr().out
    assert "opened a new one with the saved login and going on" in said, said[-2000:]
    auth = {p["url"].replace(demo.url, "") for p in out["app_map"] if p.get("auth") and not p.get("error")}
    assert {"/dashboard", "/settings", "/reports"} <= auth, auth  # (was: the run ended - nothing after the close)
    assert not [p for p in out["app_map"] if "closed" in (p.get("error") or "")]  # (never a page that 'did not load')
    failed = [i["url"].replace(demo.url, "") for i in out["crawl_issues"] if i["type"] == "page_failed"]
    assert failed == ["/missing"], failed  # (only DemoShop's planted 404 - never the page the window closed on)
    assert out["login"]["logged_in"] and (tmp_path / ".private" / "auth.json").exists()


def test_the_next_test_gets_a_new_browser_when_the_window_was_closed(tmp_path, monkeypatch):
    from backend.agents.executor import _read, _run_pytest
    from backend.agents.script_generator import TEMPLATES
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)  # (one browser: the second test needs the one that was closed)

    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = b"<title>Hi</title><h1>Hello</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    run = tmp_path / "run1"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    shutil.copy(TEMPLATES / "conftest.py", tests / "conftest.py")
    shutil.copy(TEMPLATES / "pytest.ini", tests / "pytest.ini")
    (tests / "test_window.py").write_text(
        f"URL = {url!r}\n\n\n"
        "def test_a_person_closes_the_window(page):\n    page.goto(URL)\n    assert page.title() == 'Hi'\n"
        "    page.context.browser.close()\n\n\n"
        "def test_the_next_one_still_runs(page):\n    page.goto(URL)\n"
        "    assert page.locator('h1').inner_text() == 'Hello'\n", encoding="utf-8")
    try:
        state = {"url": url + "/", "crawl": {"approved_hosts": ["127.0.0.1"]}, "app_map": [], "login": {}}
        _run_pytest(state, tests, run / "results.jsonl", run / "shots")
        got = {r["test"]: r for r in _read(run / "results.jsonl")}
    finally:
        srv.shutdown()
    nxt = got.get("test_the_next_one_still_runs") or {}
    assert nxt.get("outcome") == "passed", json.dumps(nxt)[:800]  # (was: 'Target page, context or browser ... closed')
