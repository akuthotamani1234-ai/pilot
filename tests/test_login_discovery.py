"""Login + discovery against the local DemoShop (tests/demo_app.py) in a real, hidden Chromium.
No internet needed. Takes about half a minute."""
import json

import pytest
from playwright.sync_api import sync_playwright

from backend.auth import log_in, login_form, looks_logged_out
from backend.config import settings
from backend.safety import Scope
from tests.demo_app import PASSWORD, USER, DemoApp

FORM = {"user": "#username", "password": "#password", "submit": "#sign-in"}


@pytest.fixture(scope="module")
def demo():
    app = DemoApp().start()
    yield app
    app.stop()


@pytest.fixture  # (per test: discovery starts its own Playwright, which can't run inside another one)
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


def _login(browser, demo, path="/login", user=USER, password=PASSWORD):
    context = browser.new_context()
    tab, res = log_in(context, demo.url + path, FORM, user, password, Scope(demo.url))
    return context, tab, res


def test_login_form_is_found_from_labels_and_types():
    page = {"forms": [{"fields": [{"type": "text", "selector": "#q", "name": "q", "label": "Search"},
                                  {"type": "text", "selector": "#username", "name": "username", "label": "Username"},
                                  {"type": "password", "selector": "#password"}],
                       "submit": {"selector": "#sign-in", "text": "Sign in"}}]}
    assert login_form(page) == FORM  # the user box by its name, not just the first text box
    no_form = {"forms": [], "inputs": [{"type": "email", "selector": "#e"}, {"type": "password", "selector": "#p"}],
               "buttons": [{"text": "Log in", "selector": "#go"}]}
    assert login_form(no_form) == {"user": "#e", "password": "#p", "submit": "#go"}  # single-page app without <form>
    signup = {"forms": [{"fields": [{"type": "email", "selector": "#e"}, {"type": "password", "selector": "#p1"},
                                    {"type": "password", "selector": "#p2"}], "submit": {"selector": "#r"}}]}
    assert login_form(signup) is None  # two password boxes = sign-up, not a login


def test_login_success_needs_evidence_and_the_session_holds(browser, demo):
    context, tab, res = _login(browser, demo)
    assert res["outcome"] == "success" and res["logged_in"]
    assert "the password box is gone" in res["evidence"]
    assert any("address changed" in e or "log-out" in e for e in res["evidence"])
    assert "still logged in after opening the page again" in res["evidence"]
    assert PASSWORD not in json.dumps(res)  # never recorded
    other = context.new_page()  # session preserved: another tab of the same browser session is logged in
    other.goto(demo.url + "/settings")
    assert other.url.endswith("/settings") and not looks_logged_out(other, FORM)
    demo.expire_sessions()  # the server ends the session -> detected
    other.goto(demo.url + "/reports")
    assert looks_logged_out(other, FORM)
    context.close()


SIGNUP_PAGE = """<form>
  <input formcontrolname="email" type="email" placeholder="email">
  <input formcontrolname="password" type="password"><input formcontrolname="confirm" type="password">
  <label>Male</label><input class="mt-3" type="radio" value="Male" formcontrolname="gender">
  <label>Female</label><input class="mt-3" type="radio" value="Female" formcontrolname="gender">
  <div><input type="checkbox" formcontrolname="required"></div> I am 18 or older
  <div style="position:relative"><input id="terms" type="checkbox" required>
    <span style="position:absolute;left:0;top:0;width:40px;height:40px;background:#fff"></span></div>
  <button type="button">Register</button></form>"""


def test_signup_form_is_filled_like_a_person_including_bare_and_covered_checkboxes(browser):
    """Angular-style form: no ids / names, a checkbox whose only 'text' is its value 'on', and a checkbox the
    site draws its own box over. Every box must be filled and ticked (the form is NOT sent)."""
    from backend.agents.discovery import EXTRACT_JS, _fill_signup, _signup_values
    tab = browser.new_page()
    tab.set_content(SIGNUP_PAGE)
    sels = [i["selector"] for i in tab.evaluate(EXTRACT_JS)["inputs"]]
    assert not any(":has-text" in s for s in sels if s), sels  # a box has no text to find it by
    form, data, used_username, why = _fill_signup(tab, _signup_values())
    assert why == "" and form
    assert tab.locator("input[formcontrolname=required]").is_checked()
    assert tab.locator("#terms").is_checked()
    assert tab.evaluate("() => [...document.querySelectorAll('input[type=radio]')].filter(r => r.checked).length") == 1
    tab.close()


SHOP_TOP = "<html><body><h3>Welcome to the Test Store!</h3>"
SHOP = {
    "/login": SHOP_TOP + """<div><h2>Returning customer</h2><form action="/login">
  <label for="ln">Login Name</label><input id="ln" name="loginname"><label for="pw">Password</label>
  <input id="pw" type="password" name="password"><button type="submit">Login</button></form></div>
<div><h2>I am a new customer</h2><p>Register Account: create an account to shop faster.</p>
  <button type="button" onclick="location='/register'">Continue</button></div></body></html>""",
    "/register": SHOP_TOP + """<form id="reg" onsubmit="event.preventDefault(); const f = this;
    const bad = [...f.querySelectorAll('[data-need]')].filter(i => !i.value || (i.type === 'checkbox' && !i.checked));
    if (bad.length || f.pw.value !== f.pw2.value) { document.getElementById('msg').textContent =
      'Error: ' + (bad.length ? bad[0].name + ' must be filled in!' : 'Passwords do not match!'); return; }
    location = STATUS;">
  <label for="fn">First Name</label><input id="fn" name="firstname" data-need>
  <label for="em">E-Mail</label><input id="em" type="email" name="email" data-need>
  <label for="a1">Address 1</label><input id="a1" name="address_1" data-need>
  <label for="ci">City</label><input id="ci" name="city" data-need>
  <label for="zp">ZIP Code</label><input id="zp" name="postcode" data-need>
  <label for="co">Country</label><select id="co" name="country_id"><option value="">Select</option>
    <option value="222" selected>United Kingdom</option><option value="223">United States</option></select>
  <label for="lg">Login Name</label><input id="lg" name="loginname" data-need>
  <label for="pw">Password</label><input id="pw" name="pw" type="password" data-need>
  <label for="pw2">Password Confirm</label><input id="pw2" name="pw2" type="password" data-need>
  <label><input type="checkbox" name="agree" data-need> I have read and agree to the Privacy Policy</label>
  <button type="submit">Continue</button></form><p id="msg" class="alert alert-error"></p></body></html>""",
    "/created": SHOP_TOP + "<h1>Your Account Has Been Created!</h1></body></html>",
    "/taken": SHOP_TOP + "<p class='alert alert-error'>Error: E-Mail Address is already registered!</p></body></html>",
    # a login page with no way to a sign-up form: its login form must never be sent as a 'sign-up'
    "/login-only": SHOP_TOP + """<div><h2>Returning customer</h2><form action="/login-only">
  <label for="ln">Login Name</label><input id="ln" name="loginname"><label for="pw">Password</label>
  <input id="pw" type="password" name="password"><button type="submit">Login</button></form>
  <p class="alert alert-error">Error: Incorrect login or password provided.</p></div></body></html>""",
}


@pytest.fixture
def shop():
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.server.requests.append(self.path)
            path = self.path.split("?")[0]
            body = SHOP.get(path, "<p>not found</p>").replace("STATUS", f"'{self.server.after}'").encode()
            self.send_response(200 if path in SHOP else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.after, srv.requests = "/created", []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def test_signing_up_from_a_login_page_and_only_new_evidence_counts(browser, shop):
    """automationteststore.com: 'Login or register' opens the LOGIN page; the sign-up form is behind 'I am a new
    customer -> Continue'. And 'Welcome to the store' on every page is no proof that an account was created."""
    from backend.agents.discovery import _create_account, _signup_url
    url = f"http://127.0.0.1:{shop.server_address[1]}"
    links = [{"href": url + "/login", "text": "Login or register"}, {"href": url + "/register", "text": "Create an account"}]
    assert _signup_url({"links": links}, url + "/") == url + "/register"  # the pure sign-up link first
    assert _signup_url({"links": links[:1]}, url + "/") == url + "/login"
    made, why = _create_account(browser, url + "/login")  # from the login page on to the sign-up form, filled, sent
    assert made and why == "", why
    shop.after = "/taken"  # the website refuses it - while still saying "Welcome" on the page
    made, why = _create_account(browser, url + "/login")
    assert made is None and "already registered" in why, why
    # a login page with no way to a sign-up form: said honestly - its login error is not 'the sign-up was refused'
    shop.requests.clear()
    made, why = _create_account(browser, url + "/login-only")
    assert made is None and "could not be reached" in why and "Incorrect login" not in why, why
    assert not any("loginname=" in r for r in shop.requests), shop.requests  # the login form was never sent


def test_a_person_completes_the_one_time_code_and_the_tester_verifies_the_login(browser, demo):
    """MFA is never bypassed: with a visible browser the tester WAITS for a person to type the code, then checks the
    login really worked. Here the 'person' types the code in the page itself (as someone would in the window)."""
    from backend.auth import wait_for_person
    from tests.demo_app import MFA_CODE
    context, tab, res = _login(browser, demo, "/mfa/login")
    assert res["outcome"] == "mfa_required" and not res["logged_in"]
    assert MFA_CODE not in json.dumps(res)
    tab.evaluate("code => setTimeout(() => { document.querySelector('[name=otp]').value = code;"
                 " document.querySelector('#mfa').submit(); }, 1500)", MFA_CODE)
    done = wait_for_person(tab, FORM, seconds=30)
    assert done and done["outcome"] == "success" and done["logged_in"]
    assert any("a person completed" in e for e in done["evidence"])
    assert "still logged in after opening the page again" in done["evidence"]
    context.close()
    context, tab, res = _login(browser, demo, "/mfa/login")  # nobody types the code: the tester gives up, unbypassed
    assert wait_for_person(tab, FORM, seconds=4) is None
    context.close()


def test_wrong_password_mfa_and_captcha_are_reported_not_bypassed(browser, demo):
    for path, password, outcome in (("/login", "wrong-password", "invalid_credentials"),
                                    ("/mfa/login", PASSWORD, "mfa_required"),
                                    ("/captcha/login", PASSWORD, "captcha")):
        context, tab, res = _login(browser, demo, path, password=password)
        assert res["outcome"] == outcome and not res["logged_in"], (path, res)
        context.close()


def test_discovery_logs_in_and_records_route_coverage(demo, tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    monkeypatch.setattr(settings, "test_username", USER)
    monkeypatch.setattr(settings, "test_password", PASSWORD)
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "max_pages", 30)
    monkeypatch.setattr(settings, "pattern_samples", 3)
    monkeypatch.setenv("TEST_USERNAME", USER)
    monkeypatch.setenv("TEST_PASSWORD", PASSWORD)
    demo.visited.clear()
    out = discovery_agent({"url": demo.url, "run_dir": str(tmp_path), "site_key": "demo", "log": []})

    urls = {p["url"].replace(demo.url, "") or "/" for p in out["app_map"]}
    auth = {p["url"].replace(demo.url, "") for p in out["app_map"] if p.get("auth")}
    assert {"/", "/about", "/contact", "/products", "/login"} <= urls
    assert {"/dashboard", "/settings", "/reports"} <= auth           # the app behind the login was explored
    assert sum(1 for u in urls if u.startswith("/about")) == 1       # ?utm_source / #team = the same page
    assert "/delete-all" not in demo.visited and "/logout" not in demo.visited  # dangerous links never opened
    assert out["login"]["outcome"] == "success" and out["login"]["required"] is False

    crawl = json.loads((tmp_path / "crawl.json").read_text(encoding="utf-8"))
    reasons = {s["url"].replace(demo.url, ""): s["reason"] for s in crawl["skipped"]}
    assert "change data" in reasons["/delete-all"] and "file" in reasons["/files/manual.pdf"]
    assert any("same address pattern" in r for r in reasons.values())  # /docs?id=1,2,3... stopped after a sample
    assert [r["url"].replace(demo.url, "") for r in crawl["redirected_out"]] == ["/redirect-out"]
    assert crawl["external_links"] == 1 and crawl["limit_reached"] is False
    assert (tmp_path / ".private" / "auth.json").exists()  # the saved login for the tests: not in the served folder
    assert PASSWORD not in (tmp_path / "login.json").read_text(encoding="utf-8")
    assert PASSWORD not in (tmp_path / "app_map.json").read_text(encoding="utf-8")


def test_discovery_reports_the_page_limit(demo, tmp_path, monkeypatch):
    from backend.agents.discovery import discovery_agent
    monkeypatch.setattr(settings, "test_username", "")
    monkeypatch.setattr(settings, "test_password", "")
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "max_pages", 3)
    out = discovery_agent({"url": demo.url, "run_dir": str(tmp_path), "site_key": "demo", "log": []})
    assert len(out["app_map"]) == 3
    assert out["crawl"]["limit_reached"] and out["crawl"]["not_visited_count"] > 0
    assert "STOPPED AT THE PAGE LIMIT" in out["log"][-1] or any("PAGE LIMIT" in l for l in out["log"])
