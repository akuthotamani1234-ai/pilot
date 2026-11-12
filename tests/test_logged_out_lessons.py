"""What the OrangeHRM run of Nov 2, 2026 (runs/opensource-demo.orangehrmlive.com_20261102_165226) got wrong - each one
fixed and kept fixed here:
  * at 17:32 the website ended the test account's session for all 3 browsers; every later test saw only the login
    page: 343 of 347 failures, and 5 'website bugs' (the 3 'password empty' data tests, 2 journeys) that were the
    login page. The tests now sign in again like the crawler does, or are inconclusive - never the website's failure;
  * a pair test ('Confirm Password' different from 'Current Password') clicked Save on OrangeHRM's 'Change Password'
    WITHOUT the write guard: the form has no method (Vue sends it), and only a 'post' form got the guard. Its two boxes
    also had one address, and the confirm box was paired with the CURRENT password;
  * the laptop went to sleep in the middle of the re-run (18:26 - 19:58): the PC now stays awake while a run goes."""
import json
from pathlib import Path

import pytest

from backend.config import settings
from tests.demo_app import PASSWORD, USER, DemoApp


def _password_page(method, boxes):
    form = {"selector": "form >> nth=0", "method": method, "submit": {"selector": "button.save", "text": "Save"},
            "fields": [{"selector": s, "type": "password", "label": label} for label, s in boxes]}
    return {"url": "https://hr.test/web/index.php/pim/updatePassword", "slug": "pw", "auth": True, "forms": [form],
            "inputs": [], "buttons": []}


BOXES = [("Current Password", "#current"), ("Password", "#new"), ("Confirm Password", "#confirm")]


def _confirm_cases(page):
    from backend import form_rules
    return [c for c in form_rules.pair_cases([page]) if c["spec"]["rule"] == "confirm"]


def test_a_form_without_a_method_gets_the_write_guard_in_its_pair_test(monkeypatch):
    from backend import form_rules
    monkeypatch.setattr(form_rules, "writes_allowed", lambda: False)
    [case] = _confirm_cases(_password_page("script", BOXES))
    assert case["spec"]["guard"] is True  # (was: False - 'Save' was clicked for real on the live demo)
    assert (case["spec"]["a_name"], case["spec"]["b_name"]) == ("Password", "Confirm Password")  # (was: 'Current')
    assert "_check_rule(page, R, write_guard)" in form_rules.rules_script([case], [])
    [search] = _confirm_cases(_password_page("get", BOXES))
    assert search["spec"]["guard"] is False  # a GET form only reads: it is sent normally
    same = [(label, "input.oxd-input.oxd-input--active") for label, _ in BOXES]
    assert not _confirm_cases(_password_page("script", same))  # (was: both values typed into the same box)


def test_the_pc_stays_awake_while_a_run_goes(monkeypatch, tmp_path):
    from backend import runctl
    runctl._keep_awake(True)  # (the real Windows call: no error)
    runctl._keep_awake(False)
    calls = []
    monkeypatch.setattr(runctl, "_keep_awake", calls.append)
    runctl.reset()
    calls.clear()
    runctl.start_watchers(tmp_path, 0)
    runctl.request_stop("user_stop", "the test ends the watcher")
    runctl.finished()
    runctl.reset()
    assert calls[:1] == [True] and calls[1] is False  # awake from the start of the run to its end


GENERATED = '''
from playwright.sync_api import expect


def test_dashboard(page):
    page.goto("{url}/dashboard")
    expect(page.locator("body")).to_contain_text("Welcome back")


def test_reports(page):
    page.goto("{url}/reports")
    expect(page.locator("#report")).to_be_visible()
'''


def _run(demo, tmp_path, monkeypatch, password, tests=GENERATED):
    """A run whose saved login the website has ended (like OrangeHRM at 17:32), executed like a normal run."""
    from playwright.sync_api import sync_playwright

    from backend.agents.executor import execution_agent
    from backend.agents.script_generator import TEMPLATES
    run = tmp_path / "run"
    gen = run / "generated_tests"
    gen.mkdir(parents=True)
    for name in ("conftest.py", "pytest.ini"):
        (gen / name).write_text((TEMPLATES / name).read_text(encoding="utf-8"), encoding="utf-8")
    (gen / "test_logged_in.py").write_text(tests.format(url=demo.url), encoding="utf-8")
    auth = run / ".private" / "auth.json"
    auth.parent.mkdir()
    with sync_playwright() as pw:  # (the crawler's login)
        browser = pw.chromium.launch()
        context = browser.new_context()
        tab = context.new_page()
        tab.goto(demo.url + "/login")
        tab.fill("#username", USER)
        tab.fill("#password", PASSWORD)
        tab.click("#sign-in")
        tab.wait_for_url("**/dashboard")
        context.storage_state(path=str(auth))
        browser.close()
    demo.expire_sessions()  # the website ends every session before the tests start
    old = json.loads(auth.read_text(encoding="utf-8"))["cookies"]
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)
    monkeypatch.setenv("TEST_USERNAME", USER)
    monkeypatch.setenv("TEST_PASSWORD", password)
    login_page = {"url": demo.url + "/login", "final_url": demo.url + "/login", "inputs": [], "buttons": [],
                  "forms": [{"selector": "#login-form", "method": "post", "submit": {"selector": "#sign-in",
                                                                                     "text": "Sign in"},
                             "fields": [{"name": "username", "type": "text", "selector": "#username",
                                         "label": "Username"},
                                        {"name": "password", "type": "password", "selector": "#password",
                                         "label": "Password"}]}]}
    out = execution_agent({"run_dir": str(run), "url": demo.url, "crawl": {"approved_hosts": ["127.0.0.1"]}, "log": [],
                           "login": {"logged_in": True, "page": demo.url + "/login"}, "app_map": [login_page]})
    return {r["test"]: r for r in out["results"]}, old, auth


@pytest.fixture
def demo():
    app = DemoApp().start()
    yield app
    app.stop()


@pytest.mark.slow
def test_the_tests_sign_in_again_when_the_website_ended_the_session(demo, tmp_path, monkeypatch):
    r, old, auth = _run(demo, tmp_path, monkeypatch, PASSWORD)
    assert r["test_dashboard"]["outcome"] == "passed", r["test_dashboard"]  # (was: failed on the login page)
    assert any("Signed in again" in s["text"] for s in r["test_dashboard"]["live_steps"])
    assert r["test_reports"]["outcome"] == "passed"  # the next test keeps the new login
    assert json.loads(auth.read_text(encoding="utf-8"))["cookies"] != old  # shared with the other browsers
    assert PASSWORD not in (Path(tmp_path) / "run" / "results.json").read_text(encoding="utf-8")


@pytest.mark.slow
def test_a_test_that_cannot_sign_in_again_is_inconclusive_never_the_websites_failure(demo, tmp_path, monkeypatch):
    one = GENERATED.split("\n\n\ndef test_reports")[0] + "\n"
    r, _old, _auth = _run(demo, tmp_path, monkeypatch, "wrong-password", tests=one)
    res = r["test_dashboard"]
    assert res["outcome"] == "inconclusive" and "logged out" in res["error"], res  # (was: failed -> 'website bug')
    from backend.agents.failure_analysis import classify
    assert classify(res)[0] == "inconclusive"
