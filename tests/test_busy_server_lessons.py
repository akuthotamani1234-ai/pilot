"""A run that tested nothing because the website's server was busy (automationexercise.com, Nov 2, 2026, 20:37,
runs/automationexercise.com_20261102_203659): it ended after 2 minutes with 1 page and 'Insufficient Evidence'.
  * the start page was on the screen (its screenshot shows the menu, the categories and the products), but a file the
    busy server never sent kept it 'loading', so after 20 s + 40 s it 'did not open' - and with no page there was
    nothing to test. The product pictures were missing too; 10 minutes later the same page loaded in 8 s.
  * the generated tests open pages the same way: they would have failed on pages a person could use.
Each test here opens its own browser (the crawler starts its own Playwright: two at once in one thread is refused)."""
import http.server
import threading
import time
from urllib.parse import urlparse

import pytest


def test_the_crawl_tests_a_page_that_shows_while_one_file_never_comes(tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    from backend.agents.reporter import limits_hit
    from backend.config import settings
    release = threading.Event()
    pages = {"/": "<title>Home</title><h1>Home</h1><a href='/b'>B</a><script src='/stuck.js'></script>",
             "/b": "<title>B</title><h1>B</h1><p>the next page</p>", "/stuck.js": ""}

    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                release.wait(2)  # the first try times out; the retry still receives the page
            if path == "/stuck.js":
                release.wait(60)  # (the busy server: it never comes while the page is read)
            body = pages.get(path)
            data = (body or "").encode()
            try:
                self.send_response(404 if body is None else 200)
                self.send_header("Content-Type", "text/javascript" if path.endswith(".js") else "text/html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                pass  # (the browser gave up on it)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(settings, "page_timeout_ms", 1500)
        monkeypatch.setattr(settings, "max_interactions_per_page", 0)
        monkeypatch.setattr(settings, "mobile_check", False)
        out = discovery_agent({"url": f"http://127.0.0.1:{srv.server_address[1]}/", "run_dir": str(tmp_path),
                               "site_key": "s", "log": []})
    finally:
        release.set()
        srv.shutdown()
    home = out["app_map"][0]
    assert not home.get("error") and home.get("still_loading") and home.get("title") == "Home", home.get("error")
    assert "/b" in [urlparse(p["url"]).path for p in out["app_map"]]  # (was: 1 page - the run tested nothing)
    assert not [i for i in out["crawl_issues"] if i["type"] == "page_failed"]
    assert len(out["crawl"]["still_loading"]) == 1
    assert "still_loading" in [x["id"] for x in limits_hit({"crawl": out["crawl"]}, tmp_path)]  # (said in the report)


def test_a_slow_answer_to_a_timed_out_load_does_not_break_the_next_load():
    """The checkout probe's handler of a load that timed out still waits for the slow server; its late error ('Route
    is already handled') reached the next load - the crawl's retry of the same page - and failed it (or dropped the
    start page: the run tested nothing). The next load opens."""
    from playwright.sync_api import TimeoutError as PageTimeout, sync_playwright

    from backend.payment_nav import navigate_for_crawl
    release = threading.Event()

    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/slow":
                release.wait(3)  # (later than the load waits)
            elif self.path == "/next":
                time.sleep(1)  # (still opening when the late error arrives)
            data = b"<title>Next</title><h1>Next</h1>"
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                pass

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            with pytest.raises(PageTimeout):
                navigate_for_crawl(page, base + "/slow", timeout=1000)
            response, blocked = navigate_for_crawl(page, base + "/next", timeout=15000)
            assert response is not None and response.status == 200 and not blocked
            assert page.title() == "Next"
            browser.close()
    finally:
        release.set()
        srv.shutdown()


def _conftest_code(*names):
    """Constants / functions of templates/conftest.py (read, not imported: importing it would patch Playwright)."""
    import ast
    from pathlib import Path
    src = Path("backend/templates/conftest.py").read_text(encoding="utf-8")
    return "\n\n".join(ast.get_source_segment(src, n) for n in ast.parse(src).body
                       if getattr(n, "name", None) in names
                       or isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in names)


def test_a_generated_test_uses_a_page_that_shows_while_one_file_never_comes():
    import re

    import playwright.sync_api as pw
    from playwright.sync_api import Page, sync_playwright
    ns ={"time": time, "_pw": pw, "NAV_TIMEOUT_MS": 30000, "re": re, "urlparse": urlparse, "pytest": pytest,
          "ALLOWED_HOSTS": [], "_CURRENT": {"item": None}}
    # (and what tells a page that did not open from a website that went down - advantageonlineshopping.com)
    exec(_conftest_code("CLOSE_CONSENT_JS", "SHOWS_JS", "UNREACHABLE", "_DOWN", "NOT_RUN_DOWN", "_the_website",
                        "_did_not_open", "_patched_goto"), ns)
    goto = ns["_patched_goto"](Page.goto)

    def site(route):
        if route.request.url.endswith("/stuck.js"):
            return  # (the busy server never sends it)
        body = "" if route.request.url.endswith("/empty") else "<h2>ALL PRODUCTS</h2><div class='productinfo'>Blue Top</div>"
        route.fulfill(status=200, content_type="text/html",
                      body=f"<!doctype html><html><body>{body}<script src='/stuck.js'></script></body></html>")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.route("http://shop.test/**", site)
        try:
            resp = goto(page, "http://shop.test/products", timeout=1500)
            assert resp is not None and resp.status == 200  # (was: TimeoutError - the test failed on a page that showed)
            assert page.locator(".productinfo").count() == 1
            with pytest.raises(pw.TimeoutError):  # nothing on it: that page did not open
                goto(page, "http://shop.test/empty", timeout=1500)
        finally:
            browser.close()


def test_a_request_already_settled_by_playwright_does_not_fail_the_next_page_load():
    """A slow page: its first navigation times out while the checkout guard is still fetching it, Playwright lets
    the route through, and the guard's late answer raised 'Route is already handled!' - which Playwright passed to
    the retry's page.goto, so a page that did open was reported as failed (or lost). The late answer is now left
    alone; any other routing error still surfaces."""
    from backend.payment_nav import _settle

    calls = []

    def settled(*a, **k):
        calls.append((a, k))
        raise RuntimeError("Route.continue_: Route is already handled!")

    _settle(settled, status=200)
    assert calls == [((), {"status": 200})]

    def broken():
        raise RuntimeError("Target page, context or browser has been closed")

    with pytest.raises(RuntimeError, match="has been closed"):
        _settle(broken)


def test_console_check_does_not_report_a_javascript_defect_on_navigation_timeout(capsys):
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    from backend.agents.script_generator import site_script

    class SlowPage:
        def goto(self, _url):
            raise PlaywrightTimeoutError("Page.goto: Timeout 30000ms exceeded.")

    page = {"slug": "dashboard", "url": "http://127.0.0.1/dashboard"}
    generated = {}
    exec(compile(site_script([page]), "test_site.py", "exec"), generated)
    check = generated["test_no_console_errors"]
    check(SlowPage(), [], page)
    assert "[qa-inconclusive] Navigation timed out" in capsys.readouterr().out
    with pytest.raises(AssertionError, match="real script error"):
        check(SlowPage(), ["real script error"], page)
