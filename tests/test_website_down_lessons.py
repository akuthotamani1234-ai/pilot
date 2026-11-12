"""advantageonlineshopping.com, Nov 3, 2026 (runs/www.advantageonlineshopping.com_20261103_122013):
  * the website went down for everyone during the tests (connection refused, checked from outside): 138 tests
    FAILED one after another, each waiting for it - and the retries would have waited for all of them again;
  * 3 AI journeys crashed on `to_have_count(lambda c: c > 0)`; 4 expected 'https://site/' on its home page
    'https://site/#/' (an AngularJS website);
  * "no sign-up page was found": the login was found on the first page, its #/register only later - nothing behind
    the login was tested."""
import http.server
import re
import shutil
import threading
import time

from backend.config import settings


def _server(handler_cls):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _sandbox(tmp_path, files: dict):
    from backend.agents.script_generator import TEMPLATES
    run = tmp_path / "run1"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    shutil.copy(TEMPLATES / "conftest.py", tests / "conftest.py")
    shutil.copy(TEMPLATES / "pytest.ini", tests / "pytest.ini")
    for name, code in files.items():
        (tests / name).write_text(code, encoding="utf-8")
    return run, tests


def test_a_website_that_goes_down_mid_run_leaves_tests_not_run_never_failed(tmp_path, monkeypatch):
    from backend.agents import executor
    from backend.excel import case_result
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)
    state = {}

    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = b"<title>Shop</title><h1>Shop</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            if self.path.startswith("/p1"):  # the website goes down right after the first test's page
                threading.Thread(target=lambda: (state["srv"].shutdown(), state["srv"].server_close())).start()

        def log_message(self, *a):
            pass
    srv, url = _server(Site)
    state["srv"] = srv
    code = f"from playwright.sync_api import expect\n\nURL = {url!r}\n" + "".join(
        f"\n\ndef test_page_{n}(page):\n    page.goto(URL + '/p{n}')\n    expect(page).to_have_title('Shop')\n"
        for n in range(1, 7))
    run, _tests = _sandbox(tmp_path, {"test_pages.py": code})
    t0 = time.time()
    out = executor.execution_agent({"run_dir": str(run), "url": url + "/", "crawl": {"approved_hosts": ["127.0.0.1"]},
                                    "app_map": [], "login": {}, "log": []})
    took = time.time() - t0
    got = {r["test"]: r for r in out["results"]}
    assert got["test_page_1"]["outcome"] == "passed"
    for n in range(2, 7):  # (2-4: their page did not answer; 5-6: not even tried - the website was still down)
        r = got.get(f"test_page_{n}") or {}
        assert r.get("outcome") == "skipped", r
        # (a server going away answers 'connection reset' or 'socket not connected' for a moment, then 'refused')
        assert re.match(r"Not run: the website did not answer \(net::ERR_(CONNECTION_[A-Z]+|SOCKET_NOT_CONNECTED)\)",
                        r["error"]), r["error"]
    assert not [r for r in out["results"] if r["outcome"] in ("failed", "error")]  # (was: 5 x failed)
    assert took < 90, took  # (no test waited for the dead website)
    down = __import__("json").loads((run / "execution.json").read_text(encoding="utf-8"))["website_down"]
    assert down["tests"] == 5 and down["since"]
    assert "THE WEBSITE STOPPED ANSWERING" in out["log"][-1]
    status, why = case_result({"id": "x", "tests": ["test_page_5"], "files": ["test_pages.py"]}, out["results"])
    assert status == "Not run" and "did not answer" in why, (status, why)


def test_an_empty_hash_route_is_the_same_page_and_at_least_one_is_a_number(tmp_path, monkeypatch):
    from backend.agents.executor import _read, _run_pytest
    from backend.agents.script_generator import _steady
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)

    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # an AngularJS-like website: the home page moves itself to '#/'
            data = (b"<title>Shop</title><script>if (!location.hash) location.hash = '#/';</script>"
                    b"<h1>Shop</h1><a class='item' href='#/product/3'>Speaker</a><a class='item' href='#/product/4'>Mouse</a>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv, url = _server(Site)
    ai = (f"import re\nfrom playwright.sync_api import expect\n\n\ndef test_home(page):\n    page.goto({url + '/'!r})\n"
          "    expect(page).to_have_url(re.compile(%r))\n" % (url.replace('.', r'\.') + "/?$")
          + f"    expect(page).to_have_url({url + '/'!r})\n"
          "    expect(page.locator('a.item')).to_have_count(lambda c: c > 0)\n\n\n"
          f"def test_another_route_is_another_page(page):\n    page.goto({url + '/#/product/3'!r})\n"
          f"    expect(page).to_have_url({url + '/'!r}, timeout=1000)\n")
    steady = _steady(ai)
    assert ".not_to_have_count(0)" in steady and "lambda" not in steady
    run, tests = _sandbox(tmp_path, {"test_flows_ai.py": steady})
    try:
        _run_pytest({"url": url + "/", "crawl": {"approved_hosts": ["127.0.0.1"]}, "app_map": [], "login": {}},
                    tests, run / "results.jsonl", run / "shots")
        got = {r["test"]: r for r in _read(run / "results.jsonl")}
    finally:
        srv.shutdown()
    assert got["test_home"]["outcome"] == "passed", got["test_home"].get("error")
    assert got["test_another_route_is_another_page"]["outcome"] == "failed"  # ('#/product/3' is NOT the home page)


def test_a_sign_up_page_found_later_still_gets_the_test_account(tmp_path, monkeypatch, capsys):
    from backend.agents import discovery
    for page in ("https://x.test/register", "https://x.test/#/register", "https://x.test/account/sign-up?next=/"):
        assert discovery._signup_url({}, page) == page  # (by its address alone - was: only '/register/...')
    assert discovery._signup_url({}, "https://x.test/registered-users") is None
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "max_pages", 8)
    monkeypatch.setattr(settings, "auto_register", True)
    monkeypatch.setattr(settings, "test_username", "")
    monkeypatch.setattr(settings, "test_password", "")
    monkeypatch.setenv("TEST_USERNAME", "")  # (the created account is put here: put back after this test)
    monkeypatch.setenv("TEST_PASSWORD", "")
    made = []
    # (signing up itself is tested in test_login_discovery.py: here the website's sign-up 'works')
    monkeypatch.setattr(discovery, "_create_account", lambda browser, signup: made.append(signup) or (
        {"username": "qa@example.com", "email": "qa@example.com", "user_name": "", "password": "Secret1",
         "signup_page": signup}, ""))
    monkeypatch.setattr(discovery, "save_account", lambda *a, **k: None)  # (never written to accounts/)
    monkeypatch.setattr(discovery, "load_account", lambda *a, **k: None)

    class Site(http.server.BaseHTTPRequestHandler):
        def _page(self, html: bytes, status=200, headers=()):
            self.send_response(status)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_GET(self):
            logged_in = "session=ok" in (self.headers.get("Cookie") or "")
            if self.path == "/dashboard":
                if not logged_in:
                    return self._page(b"", 302, [("Location", "/")])
                return self._page(b"<title>Dashboard</title><h1>My orders</h1><a href='/orders'>Orders</a>")
            if self.path == "/orders":
                return self._page(b"<title>Orders</title><h1>Orders</h1><p>No orders yet</p>")
            if self.path == "/about":  # (only here: the way to the sign-up page)
                return self._page(b"<title>About</title><h1>About us</h1><a href='/register'>New here?</a>")
            if self.path == "/register":
                return self._page(b"<title>Register</title><h1>Create an account</h1><form method='post'>"
                                  b"<input type='email' name='email'><input type='password' name='p1'>"
                                  b"<input type='password' name='p2'><button>Register</button></form>")
            self._page(b"<title>Shop</title><h1>Shop</h1><form method='post' action='/login'><label>Email "
                       b"<input type='email' name='email' id='email'></label><label>Password <input type='password' "
                       b"name='password' id='password'></label><button id='go'>Log in</button></form>"
                       b"<a href='/about'>About</a>")

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
            if self.path == "/login" and "qa%40example.com" in body and "Secret1" in body:
                return self._page(b"", 302, [("Location", "/dashboard"), ("Set-Cookie", "session=ok; Path=/")])
            self._page(b"<title>Shop</title><p>Wrong email or password</p>", 200)

        def log_message(self, *a):
            pass
    srv, url = _server(Site)
    try:
        out = discovery.discovery_agent({"url": url + "/", "run_dir": str(tmp_path), "site_key": "late-signup-test",
                                         "log": []})
    finally:
        srv.shutdown()
    said = capsys.readouterr().out
    assert "the sign-up page was found now" in said, said[-3000:]
    assert made == [url + "/register"]
    assert out["login"]["logged_in"], out["login"]  # (was: 'no sign-up page was found' - nothing behind the login)
    auth = {p["url"].replace(url, "") for p in out["app_map"] if p.get("auth") and not p.get("error")}
    assert "/dashboard" in auth and "/orders" in auth, auth
