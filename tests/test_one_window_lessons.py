"""practicesoftwaretesting.com, Nov 3, 2026 (runs/practicesoftwaretesting.com_20261103_111740), checked by hand:
  * 7 of the 10 AI journeys failed - none on a website bug: 'text=Power Tools' matched the menu item, the page title
    and a filter (strict mode), results were counted before the search had finished, a relative address in
    to_have_url, an invented 'correct' password - and self-healing refused EVERY repair of the file because one test
    already had an `assert True`;
  * "Failed to load Google Analytics script" failed 2 journeys: the website said it because WE blocked the tracker;
  * 7 "an empty value was accepted": Angular's own check (no `required` attribute), which the browser never runs;
  * /account got net::ERR_ABORTED right after the login - the whole account area was never explored.
And the user asked for ONE window for the whole run, and 20 large test cases."""
import http.server
import json
import re
import shutil
import threading

from backend.config import settings


def test_ai_code_is_made_steady_before_it_runs():
    from backend.agents.script_generator import _steady, validate_script
    code = (
        "import re\nimport pytest\nfrom playwright.sync_api import expect\n\n\n"
        "def test_ai_flow_1(page):\n    \"\"\"Browse\"\"\"\n    page.goto('https://x.test')\n"
        "    expect(page.locator(\"text=Power Tools\")).to_be_visible()\n"
        "    expect(page.locator(\"h1, h2, h3, h4, h5, h6\")).to_contain_text('Bolt Cutters')\n"
        "    expect(page.locator(\"text=Basket\")).not_to_be_visible()\n"
        "    expect(page.locator(\"#exact\")).to_be_visible()\n"
        "    expect(page.locator(\"text=Row\")).to_have_count(3)\n"
        "    for product in ['Pliers', 'Hammer']:\n"
        "        assert page.locator(f\"a:has-text(\\\"{product}\\\")\").count() == 0, f\"Unexpected '{product}'\"\n"
        "    try:\n        page.wait_for_url(lambda url: 'login' not in url, timeout=5000)\n        assert True\n"
        "    except Exception:\n        pass\n")
    out = _steady(code)
    assert validate_script(out) is None
    assert 'expect(page.locator("text=Power Tools >> visible=true >> nth=0")).to_be_visible()' in out
    assert 'expect(page.locator("h1, h2, h3, h4, h5, h6 >> visible=true >> nth=0")).to_contain_text' in out
    assert 'expect(page.locator("text=Basket >> visible=true >> nth=0")).not_to_be_visible()' in out
    assert 'expect(page.locator("#exact")).to_be_visible()' in out  # (an exact address: unchanged)
    assert 'expect(page.locator("text=Row")).to_have_count(3)' in out  # (a count: never narrowed to one)
    assert ("expect(page.locator(f\"a:has-text(\\\"{product}\\\")\"), f\"Unexpected '{product}'\").to_have_count(0)"
            in out)  # (it waits until the search results are shown)
    assert not re.search(r"^\s*assert True\s*$", out, re.M) and "pass  # (was `assert True`" in out


def test_a_repair_is_refused_only_for_a_cheat_the_repair_adds():
    from backend.agents.self_healing import _safe_repair
    old = ("import pytest\nfrom playwright.sync_api import expect\n\n\n"
           "def test_ai_flow_2(page):\n    \"\"\"Register\"\"\"\n    page.goto('https://x.test')\n"
           "    try:\n        page.wait_for_url(lambda url: 'register' not in url, timeout=3000)\n        assert True\n"
           "    except Exception:\n        pass\n\n\n"
           "def test_ai_flow_5(page):\n    \"\"\"Browse\"\"\"\n    page.goto('https://x.test')\n"
           "    expect(page.locator('text=Power Tools')).to_be_visible()\n")
    swap = old.replace("'text=Power Tools'", "'text=Power Tools >> visible=true >> nth=0'")
    assert _safe_repair(old, swap) is None  # (was: 'an assert of a constant' - test_ai_flow_2 already had it)
    cheat = swap.replace("    expect(page.locator(", "    assert True\n    expect(page.locator(")
    assert "constant" in (_safe_repair(old, cheat) or "")  # (a NEW one is still refused)


def test_twenty_ai_journeys_are_written_five_at_a_time_and_one_bad_answer_loses_only_its_five(monkeypatch):
    from backend.agents import script_generator as sg
    from backend.agents.test_design import LARGE
    assert LARGE == 20

    def answer(prompt, **k):
        ids = list(dict.fromkeys(re.findall(r'"id": "(ai_flow_\d+)"', prompt)))
        if "ai_flow_6" in ids or "def test_" in prompt:  # (the 2nd batch: bad code, also when asked to fix it)
            return "```python\nimport os\n\ndef test_ai_flow_6(page):\n    os.remove('x')\n```"
        tests = "".join(f"\n\n@pytest.mark.guest\ndef test_{i}(page):\n    \"\"\"Journey {i}\"\"\"\n"
                        f"    page.goto(URL)\n    assert _count(page) == {len(ids)}\n" for i in ids)
        return (f"```python\nimport re\nimport pytest\nfrom playwright.sync_api import expect\n\nURL = 'https://x.test/'"
                f"\n\n\ndef _count(page):\n    return {len(ids)}\n{tests}```")
    monkeypatch.setattr(sg, "ask_llm", answer)
    page = {"slug": "home", "url": "https://x.test/", "buttons": [], "inputs": [], "forms": [], "links": []}
    flows = [{"id": f"ai_flow_{n}", "title": f"Journey {n}", "guest": True, "pages": ["home"], "test_data": "",
              "steps": ["Open", "Check"], "expected": "Shown"} for n in range(1, 21)]
    code, lost, why = sg._llm_flows_in_batches(flows, {"home": page})
    assert lost == [f"ai_flow_{n}" for n in range(6, 11)] and "Banned import" in why
    assert sg.validate_script(code) is None
    assert len(re.findall(r"^def test_ai_flow_\d+\(page\):", code, re.M)) == 15
    assert code.count("def _said(page):") == 1 and code.count("from playwright.sync_api import expect") == 1
    # each answer's own helper stays its own (the 2nd and 3rd working answers' `_count` got their number)
    assert "def _count_2(page):" in code and "def _count_3(page):" in code and "URL_3 = " in code
    assert "assert _count_3(page) == 5" in code


def test_a_tracker_we_blocked_is_not_the_websites_error():
    from backend.safety import blocked_tracker_said
    for ours in ("Failed to load Google Analytics script", "ReferenceError: gtag is not defined",
                 "Uncaught ReferenceError: dataLayer is not defined", "adsbygoogle.push() error: No slot size"):
        assert blocked_tracker_said(ours), ours
    for theirs in ("ERROR TypeError: Cannot read properties of null (reading 'cart_items')",
                   "Failed to load resource: the server responded with a status of 500"):
        assert not blocked_tracker_said(theirs), theirs


def _serve(pages: dict, hits: dict):
    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits[self.path] = hits.get(self.path, 0) + 1
            body = pages.get(self.path)
            if callable(body):
                body = body(hits[self.path])
            if body is None:
                self.send_response(404 if self.path not in pages else 204)
                self.end_headers()
                return
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_an_empty_box_only_the_websites_code_requires_and_a_relative_address(tmp_path, monkeypatch):
    from backend.agents.executor import _read, _run_pytest
    from backend.agents.script_generator import TEMPLATES, data_script
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)
    form = ("<title>Register</title><h1>Register</h1><form novalidate>"
            "<label>Street *<input id='ng' class='form-control ng-untouched ng-pristine ng-invalid'></label>"
            "<label>House number *<input id='plain'></label>"
            "<label>Email *<input id='req' required></label></form><a href='/two'>Two</a>")
    srv, url = _serve({"/": form, "/two": "<title>Two</title><h1>Two</h1>"}, {})
    run = tmp_path / "run1"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    shutil.copy(TEMPLATES / "conftest.py", tests / "conftest.py")
    shutil.copy(TEMPLATES / "pytest.ini", tests / "pytest.ini")
    cases = [{"id": f"data_{k}_empty", "title": f"'{k}' box: leaving it empty (it is required)", "selector": f"#{k}",
              "value": "", "expect": "invalid"} for k in ("ng", "plain", "req")]
    (tests / "test_home_data.py").write_text(data_script({"url": url + "/", "auth": False}, cases), encoding="utf-8")
    (tests / "test_url.py").write_text(
        "from playwright.sync_api import expect\n\n\n"
        f"def test_relative_address(page):\n    page.goto({url + '/'!r})\n    page.locator('a').click()\n"
        "    expect(page).to_have_url('/two')  # (as the website's links write it)\n", encoding="utf-8")
    try:
        _run_pytest({"url": url + "/", "crawl": {"approved_hosts": ["127.0.0.1"]}, "app_map": [], "login": {}},
                    tests, run / "results.jsonl", run / "shots")
        got = {r["test"]: r for r in _read(run / "results.jsonl")}
    finally:
        srv.shutdown()
    out = {t: r["outcome"] for t, r in got.items()}
    assert out["test_data_ng_empty"] == "passed", got["test_data_ng_empty"]  # (Angular marks it: ng-invalid)
    assert out["test_data_req_empty"] == "passed"  # (the browser's own check, as before)
    # nothing on the box, nothing on the page: the website refuses it only when the form is sent - never a bug
    assert out["test_data_plain_empty"] == "inconclusive", got["test_data_plain_empty"]
    assert out["test_relative_address"] == "passed", json.dumps(got["test_relative_address"])[:600]


def test_a_page_load_the_browser_cancelled_is_tried_once_more(tmp_path, monkeypatch, capsys):
    """HTTP 204 the first time: Chrome cancels the navigation (net::ERR_ABORTED) - like /account while the website was
    still moving after the login. The second try opens it; it is never 'a page that did not load'."""
    from backend.agents import discovery
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "max_pages", 5)
    home = "<title>Home</title><h1>Home</h1><a href='/account'>My account</a>"
    account = lambda n: None if n == 1 else "<title>Account</title><h1>My account</h1><p>Orders</p>"  # noqa: E731
    hits = {}
    srv, url = _serve({"/": home, "/account": account}, hits)
    try:
        out = discovery.discovery_agent({"url": url + "/", "run_dir": str(tmp_path), "site_key": "t", "log": []})
    finally:
        srv.shutdown()
    pages = {p["url"].replace(url, ""): p for p in out["app_map"]}
    assert "the browser cancelled the page load" in capsys.readouterr().out  # (the first try WAS cancelled)
    assert hits.get("/account", 0) >= 2, hits
    assert "/account" in pages and not pages["/account"].get("error"), pages.get("/account")
    assert pages["/account"].get("title") == "Account"
    assert not [i for i in out["crawl_issues"] if i["type"] == "page_failed"]
