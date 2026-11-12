"""The TestOptim features that were still missing or partly there (Nov 2, 2026, night) - each checked here:
  * the login code of a 2-step login, made from the test account's authenticator key (TOTP, RFC 6238);
  * a multi-step form's later step opened directly by a new visitor: not offered (else a rule question);
  * your own tests in plain English: kept per website, designed by the AI, never dropped silently;
  * the review: untick test cases (this run), add your own tests (designed now, kept);
  * re-check after a fix: only the finding's test runs again, in the real sandbox -> fixed / still failing;
  * scheduled runs: the next time, a missed time is skipped, a test waiting behind a running one still starts.
Every website here runs on this PC."""
import http.server
import json
import shutil
import threading
import time
from datetime import datetime
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from fastapi.testclient import TestClient

from backend.config import settings

SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of the RFC 6238 test key "12345678901234567890"


def _serve(handler):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class _Site(http.server.BaseHTTPRequestHandler):
    """A tiny website: pages(path, cookies, form) -> (status, html, {header: value})."""
    pages = staticmethod(lambda path, cookies, form: (404, "<p>missing</p>", {}))

    def _answer(self, form):
        jar = SimpleCookie(self.headers.get("Cookie") or "")
        code, html, headers = self.pages(self.path.split("?")[0], {k: v.value for k, v in jar.items()}, form)
        data = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._answer({})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        self._answer({k: v[0] for k, v in parse_qs(raw).items()})

    def log_message(self, *a):
        pass


def _site(pages):
    return _serve(type("Site", (_Site,), {"pages": staticmethod(pages)}))


# ------------------------------------------------------------------ the login code from an authenticator key

def test_the_authenticator_code_is_the_one_the_app_shows():
    from backend.auth import totp
    assert totp(SECRET, at=59, digits=8) == "94287082"            # RFC 6238, appendix B
    assert totp(SECRET, at=1111111109, digits=8) == "07081804"
    assert totp(SECRET, at=59) == "287082"                        # the 6 digits an app shows
    assert totp(f"otpauth://totp/Shop:qa?secret={SECRET}&issuer=Shop&digits=8", at=59) == "94287082"
    assert totp(SECRET.lower()[:8] + " " + SECRET.lower()[8:], at=59) == "287082"  # (as copied from a setup page)


def _two_step_site():
    from backend.auth import totp

    def pages(path, cookies, form):
        if path == "/login" and form:
            ok = form.get("user") == "qa@shop.test" and form.get("password") == "Pass#123"
            return 303, "", {"Location": "/mfa" if ok else "/login", **({"Set-Cookie": "stage=mfa; Path=/"} if ok else {})}
        if path == "/login":
            return 200, ("<title>Sign in</title><form method=post action=/login><input id=user name=user>"
                         "<input id=password name=password type=password><button id=go>Sign in</button></form>"), {}
        if path == "/mfa" and form and cookies.get("stage") == "mfa":
            good = {totp(SECRET), totp(SECRET, at=time.time() - 30)}
            if form.get("code") in good:
                return 303, "", {"Location": "/home", "Set-Cookie": "who=qa; Path=/"}
            return 200, "<p>Wrong code, try again</p>" + MFA, {}
        if path == "/mfa":
            return 200, MFA, {}
        if path == "/home" and cookies.get("who") == "qa":
            return 200, "<title>Dashboard</title><h1>Dashboard</h1><a href=/logout>Log out</a>", {}
        return 303, "", {"Location": "/login"}
    return _site(pages)


MFA = ("<title>Verify</title><h1>2-step verification</h1><form method=post action=/mfa><label for=code>"
       "Verification code</label><input id=code name=code autocomplete=one-time-code><button>Verify</button></form>")


def test_a_two_step_login_types_the_authenticator_code(monkeypatch):
    from playwright.sync_api import sync_playwright

    from backend.auth import log_in
    srv, url = _two_step_site()
    form = {"user": "#user", "password": "#password", "submit": "#go"}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                monkeypatch.setattr(settings, "test_totp_secret", "")
                _tab, res = log_in(browser.new_context(), url + "/login", form, "qa@shop.test", "Pass#123")
                assert res["outcome"] == "mfa_required"  # (no key: never bypassed - as before)
                monkeypatch.setattr(settings, "test_totp_secret", SECRET)
                tab, res = log_in(browser.new_context(), url + "/login", form, "qa@shop.test", "Pass#123")
                assert res["outcome"] == "success" and res["logged_in"], res
                assert any("authenticator key" in e for e in res["evidence"]) and "/home" in tab.url
                monkeypatch.setattr(settings, "test_totp_secret", "JBSWY3DPEHPK3PXP")  # (a wrong key)
                _tab, res = log_in(browser.new_context(), url + "/login", form, "qa@shop.test", "Pass#123")
                assert res["outcome"] == "mfa_required" and "not accepted" in res["evidence"][-1], res
            finally:
                browser.close()
    finally:
        srv.shutdown()


def test_the_authenticator_key_is_a_secret():
    from backend.safety import API_KEY_ENV, SECRET_ENV, clean_env
    assert "TEST_TOTP_SECRET" in SECRET_ENV and "TEST_TOTP_SECRET" in API_KEY_ENV
    assert "TEST_TOTP_SECRET" not in clean_env({"TEST_TOTP_SECRET": SECRET, "PATH": "x"}, keep_test_account=True)
    import main
    assert "test_totp_secret" in main.SECRET_SETTINGS  # (never written to run_args.json)


# ------------------------------------------------------------------ a multi-step form's later step, opened directly

def _page(slug, url, fields=(), auth=False, fills=()):
    return {"slug": slug, "url": url, "title": slug.title(), "auth": auth, "inputs": [], "buttons": [], "links": [],
            "forms": [{"selector": "form", "method": "post", "fields": [{"selector": s, "type": "text"} for s in fields]}]
            if fields else [], "form_fills": list(fills)}


def test_the_later_steps_of_multi_step_forms_are_found():
    from backend.form_rules import step_order_cases
    sent = {"sent": True, "next_url": "http://shop.test/wizard/step2", "name": "Next"}
    pages = [_page("step1", "http://shop.test/wizard/step1", ["#name"], fills=[sent]),
             _page("step2", "http://shop.test/wizard/step2", ["#card", "#cvv"]),
             _page("pay", "http://shop.test/checkout?step=3", ["#iban"]),
             _page("first", "http://shop.test/checkout?step=1", ["#mail"]),
             _page("member", "http://shop.test/account/step-2", ["#plan"], auth=True)]
    cases = step_order_cases(pages)
    assert [c["url"] for c in cases] == ["http://shop.test/wizard/step2", "http://shop.test/checkout?step=3"]
    c = cases[0]
    assert c["kind"] == "pair" and c["guest"] and c["spec"]["fields"] == ["#card", "#cvv"]
    assert "'Next' on /wizard/step1" in c["spec"]["question"] and c["spec"]["question"].endswith("Is that allowed?")
    assert step_order_cases([_page("x", "http://shop.test/x", ["#a"])]) == []  # (no steps: nothing)


def _wizard_site():
    """/a: step 2 sends a new visitor back to step 1 (right) - /b: step 2 is offered to anyone (a question)."""
    def pages(path, cookies, form):
        for w in ("a", "b"):
            if path == f"/{w}/step1" and form:
                return 303, "", {"Location": f"/{w}/step2", "Set-Cookie": f"wiz{w}=1; Path=/"}
            if path == f"/{w}/step1":
                return 200, "<title>Step 1</title><form method=post><input id=name name=name><button>Next</button></form>", {}
            if path == f"/{w}/step2":
                if w == "a" and cookies.get("wiza") != "1":
                    return 303, "", {"Location": "/a/step1"}
                return 200, "<title>Step 2</title><form method=post><input id=card><input id=cvv><button>Pay</button></form>", {}
        if path == "/status":
            return 200, f"<title>Status</title><h1>{STATE['status']}</h1>", {}
        return 404, "<p>missing</p>", {}
    return _site(pages)


STATE = {"status": "Broken"}


def _run_dir(tmp_path: Path, url: str, files: dict) -> Path:
    """A finished run's folder, as the tester leaves it: its scripts (with the real conftest), pages and settings."""
    from backend.agents.script_generator import TEMPLATES
    run = tmp_path / "run1"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    shutil.copy(TEMPLATES / "conftest.py", tests / "conftest.py")
    shutil.copy(TEMPLATES / "pytest.ini", tests / "pytest.ini")
    for name, code in files.items():
        (tests / name).write_text(code, encoding="utf-8")
    for name, data in {"run_args.json": {"url": url + "/", "site_key": "local", "source": url, "settings": {}},
                       "crawl.json": {"approved_hosts": ["127.0.0.1"]}, "login.json": {}, "app_map.json": []}.items():
        (run / name).write_text(json.dumps(data), encoding="utf-8")
    return run


def test_a_later_step_alone_is_refused_or_asked_about_in_the_real_sandbox(tmp_path, monkeypatch):
    from backend.agents.executor import _read, _run_pytest
    from backend.agents.failure_analysis import classify
    from backend.agents.script_generator import JOURNEY_HELPERS, LINES_JS, RESULT_HELPERS, VALIDATION_JS
    from backend.form_rules import rules_script, step_order_cases
    monkeypatch.setattr(settings, "headless", True)
    srv, url = _wizard_site()
    try:
        pages = []
        for w in ("a", "b"):
            sent = {"sent": True, "next_url": f"{url}/{w}/step2", "name": "Next"}
            pages += [_page(f"{w}1", f"{url}/{w}/step1", ["#name"], fills=[sent]),
                      _page(f"{w}2", f"{url}/{w}/step2", ["#card", "#cvv"])]
        cases = step_order_cases(pages)
        header = ["import re", "import pytest", "from playwright.sync_api import expect", "", JOURNEY_HELPERS,
                  RESULT_HELPERS, f"LINES_JS = {LINES_JS!r}", f"VALIDATION_JS = {VALIDATION_JS!r}",
                  "APPROVE_JS = \"e => e.setAttribute('data-qa-approved', '1')\"", ""]
        run = _run_dir(tmp_path, url, {"test_field_rules.py": rules_script(cases, header)})
        state = {"url": url + "/", "crawl": {"approved_hosts": ["127.0.0.1"]}, "app_map": [], "login": {}}
        _run_pytest(state, run / "generated_tests", run / "results.jsonl", run / "shots")
        got = {r["test"]: r for r in _read(run / "results.jsonl")}
    finally:
        srv.shutdown()
    assert got["test_pair_step_1"]["outcome"] == "passed", got["test_pair_step_1"].get("error")  # sent back to step 1
    offered = got["test_pair_step_2"]
    assert offered["outcome"] == "failed" and "[rule]" in offered["error"], offered.get("error")
    assert classify(offered)[0] == "rule_violation"  # a question for you - never called a website bug by itself


# ------------------------------------------------------------------ re-check one bug after a fix

def test_re_check_runs_only_that_test_again_fixed_or_still_failing(tmp_path, monkeypatch):
    from backend.recheck import recheck, tests_of
    monkeypatch.setattr(settings, "headless", True)
    srv, url = _wizard_site()
    test = (f"URL = {url + '/status'!r}\n\n\ndef test_status(page):\n    page.goto(URL)\n"
            "    assert page.locator('h1').inner_text() == 'Fixed'\n\n\ndef test_other(page):\n    assert False\n")
    try:
        run = _run_dir(tmp_path, url, {"test_status.py": test})
        (run / "failures.json").write_text(json.dumps([
            {"id": 0, "source": "test", "nodeid": "test_status.py::test_status", "category": "product_defect"},
            {"id": 1, "source": "test", "nodeid": "test_status.py::test_other", "category": "test_defect"}]))
        assert tests_of(run, [0, 1]) == ["test_status.py::test_status"]  # (a broken script is no bug to re-check)
        STATE["status"] = "Broken"
        first = recheck(run, ["test_status.py::test_status"])["results"]["test_status.py::test_status"]
        STATE["status"] = "Fixed"  # (the developer fixed it)
        second = recheck(run, ["test_status.py::test_status"])["results"]["test_status.py::test_status"]
    finally:
        srv.shutdown()
    assert first["verdict"] == "still failing" and "Broken" in first["error"], first
    assert second["verdict"] == "fixed", second
    history = json.loads((run / "recheck.json").read_text(encoding="utf-8"))["test_status.py::test_status"]
    assert [h["verdict"] for h in history] == ["still failing", "fixed"]
    assert not (run / ".private").exists()


# ------------------------------------------------------------------ your own tests in plain English

def test_your_own_tests_are_kept_per_website(tmp_path, monkeypatch):
    from backend import my_tests
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    assert my_tests.site_key_of("https://shop.test:8443/x") == "shop.test_8443"
    assert my_tests.lines("- Search for 'Top'\n\n2. Open the cart\nok\nSearch for 'top'") == \
        ["Search for 'Top'", "Open the cart"]  # (bullets / numbers off, too short and repeated lines left out)
    saved = my_tests.save("shop", ["Search for 'Top'", "Open the cart"])
    assert [t["text"] for t in my_tests.add("shop", ["Log in and see the dashboard"])] == \
        ["Search for 'Top'", "Open the cart", "Log in and see the dashboard"]
    assert my_tests.load("shop")[0]["id"] == saved[0]["id"]  # (the same test keeps its id)
    assert my_tests.save("shop", []) == [] and my_tests.load("shop") == []  # (an empty box removes them)


HOME = {"slug": "home", "url": "http://shop.test/", "title": "Shop", "auth": False, "inputs": [], "buttons": [],
        "links": [], "forms": [], "headings": ["Shop"]}


def test_your_own_tests_become_test_cases_and_are_never_dropped(monkeypatch):
    from backend.agents import test_design as td
    tests = [{"id": "MY-1", "text": "Open the shop - its heading says Shop"},
             {"id": "MY-2", "text": "Add a product to the wishlist"}]
    monkeypatch.setattr(td, "llm_enabled", lambda: False)
    off = td.my_test_cases([HOME], tests, start=1)
    assert [c["kind"] for c in off] == ["mine", "mine"] and "need an AI" in off[0]["skip_reason"]

    answer = [td.AICase(title="Shop heading", steps=["Open the home page", "The heading 'Shop' is shown"], expected="Shop"),
              td.AICase(title="Wishlist", steps=["Not possible on this website", "there is no wishlist"],
                        expected="Not possible: there is no wishlist")]
    monkeypatch.setattr(td, "llm_enabled", lambda: True)
    monkeypatch.setattr(td, "ask_structured", lambda prompt, *a, **k: answer if "1. Open the shop" in prompt else [])
    cases = td.my_test_cases([HOME], tests, start=4)
    assert cases[0]["id"] == "ai_flow_4" and cases[0]["title"] == tests[0]["text"]  # (your words stay the title)
    assert cases[0]["files"] == ["test_flows_ai.py"] and cases[0]["tests"] == ["test_ai_flow_4"]
    assert cases[1]["kind"] == "mine" and "no wishlist" in cases[1]["skip_reason"]
    done = td.finalize_cases(cases, {"app_map": [HOME]})
    assert not [td.validate_case(c) for c in done if td.validate_case(c)]
    assert {c["requirement"] for c in done} == {td.MY_TEST}


def test_your_own_ai_test_marks_unsupported_exact_result_as_exploratory(monkeypatch):
    from backend.agents import test_design as td

    monkeypatch.setattr(td, "llm_enabled", lambda: True)
    monkeypatch.setattr(td, "ask_structured", lambda *a, **k: [td.AICase(
        title="Check the owner workflow", steps=["Open the shop", "Continue the workflow"],
        expected="The website says 'Saved successfully.'")])
    tests = [{"id": "MY-3", "text": "Open the shop and inspect the result"}]

    case = td.my_test_cases([HOME], tests, start=1)[0]

    assert case["type"] == "exploratory"
    assert case["expected"].startswith("Exploratory:")


def test_the_review_leaves_out_unticked_cases_and_adds_your_tests(tmp_path, monkeypatch):
    from backend import my_tests, review
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    monkeypatch.setattr(settings, "review", "on")
    monkeypatch.setattr(settings, "review_timeout_s", 30)
    run = tmp_path / "run"
    run.mkdir()
    cases = [{"tc_id": "TC-AAAAAAA1", "id": "a", "kind": "feature", "title": "Sort by price"},
             {"tc_id": "TC-AAAAAAA2", "id": "b", "kind": "cleanup", "title": "Remove the test data"},
             {"tc_id": "TC-AAAAAAA3", "id": "c", "kind": "feature", "title": "Filter by colour"}]

    def answer():  # (what the chat sends)
        asked = json.loads((run / "review_request.json").read_text(encoding="utf-8"))
        assert [c["tc_id"] for c in asked["cases"]] == ["TC-AAAAAAA1", "TC-AAAAAAA2", "TC-AAAAAAA3"]
        (run / "review_answers.json").write_text(json.dumps({"answers": {}, "leave_out": ["TC-AAAAAAA1", "TC-AAAAAAA2"],
                                                             "add_tests": ["Open the shop and see its heading"]}))
    threading.Timer(1.5, answer).start()
    out = review.review_gate_agent({"site_key": "shop", "run_dir": str(run), "test_cases": cases, "log": [],
                                    "app_map": [HOME]})
    ids = [c["tc_id"] for c in out["test_cases"]]
    assert "TC-AAAAAAA1" not in ids and "TC-AAAAAAA2" in ids  # (a staging cleanup is never left out)
    mine = [c for c in out["test_cases"] if c.get("my_test")]
    assert len(mine) == 1 and mine[0]["title"] == "Open the shop and see its heading"
    assert [t["text"] for t in my_tests.load("shop")] == ["Open the shop and see its heading"]  # (kept)
    assert "1 test(s) of your own added" in out["log"][-1]


# ------------------------------------------------------------------ scheduled runs

def test_scheduled_runs_start_when_due_and_skip_what_was_missed(tmp_path, monkeypatch):
    from backend import server
    monkeypatch.setattr(server, "SCHEDULES", tmp_path / "schedules.json")
    monkeypatch.setattr(server, "RUNS", tmp_path)
    (tmp_path / "r1").mkdir()
    (tmp_path / "r1" / "run_args.json").write_text(json.dumps({"source": "https://shop.test/", "settings": {
        "llm_provider": "none", "environment": "test", "max_pages": 5}}))
    started = []
    monkeypatch.setattr(server, "start_run", lambda req: started.append(req) or {"id": len(started)})
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    h = {"X-Agentic-QA": "1"}
    assert client.post("/api/schedules", json={"run": "r1", "every": "daily", "at": "25:00"}, headers=h).status_code == 400
    s = client.post("/api/schedules", json={"run": "r1", "every": "daily", "at": "07:00"}, headers=h).json()
    assert s["settings"]["max_pages"] == 5 and s["next"].endswith("07:00")

    nxt = server._next_time
    at = datetime(2026, 11, 2, 21, 15)  # (a Monday)
    assert nxt({"every": "daily", "at": "07:00"}, at) == datetime(2026, 11, 3, 7, 0)
    assert nxt({"every": "hourly", "at": "00:30"}, at) == datetime(2026, 11, 2, 21, 30)
    assert nxt({"every": "weekly", "at": "09:00", "day": 4}, at) == datetime(2026, 11, 6, 9, 0)  # Friday

    def at_(when):
        items = json.loads((tmp_path / "schedules.json").read_text())
        items[0]["next"] = when
        (tmp_path / "schedules.json").write_text(json.dumps(items))
    at_("2026-11-03T07:00")
    assert server.run_due_schedules(datetime(2026, 11, 3, 7, 0, 20)) == [s["id"]]  # due: started
    assert started[-1].source == "https://shop.test/" and started[-1].max_pages == 5 and started[-1].authorized
    at_("2026-11-04T07:00")
    assert server.run_due_schedules(datetime(2026, 11, 4, 9, 30)) == []  # the UI was closed at 07:00: missed
    item = json.loads((tmp_path / "schedules.json").read_text())[0]
    assert item["missed"] == 1 and item["next"] == "2026-11-05T07:00" and len(started) == 1
    # due while another test runs: it waits - and still starts when that test has finished, even an hour later
    server.jobs[999] = {"status": "running"}
    try:
        at_("2026-11-05T07:00")
        assert server.run_due_schedules(datetime(2026, 11, 5, 7, 0, 30)) == []
    finally:
        server.jobs.pop(999)
    assert server.run_due_schedules(datetime(2026, 11, 5, 8, 10)) == [s["id"]] and len(started) == 2
    assert client.delete(f"/api/schedules/{s['id']}", headers=h).json()["deleted"] == 1
