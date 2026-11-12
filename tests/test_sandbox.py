"""The sandbox around generated tests, run for real: a throw-away run folder with hostile / broken test files,
executed by the Execution Agent exactly like a normal run (hidden Chromium, local DemoShop, ~30 s)."""
import json
from pathlib import Path

import pytest

from backend.config import settings
from tests.demo_app import DemoApp

pytestmark = pytest.mark.slow  # (a real sandboxed test run: quick checks leave it out with -m "not slow")
HOSTILE = '''
import pytest
from playwright.sync_api import expect

URL = "{url}"


def test_ok(page):
    page.goto(URL)
    expect(page).to_have_title("Home - DemoShop")


def test_checks_nothing(page):
    page.goto(URL)


def test_cannot_start_programs(page):
    pytest.importorskip  # (a real script would be refused before running; here we call the runtime directly)
    import subprocess
    subprocess.run(["cmd", "/c", "echo hacked"])


def test_cannot_write_outside_the_run(page):
    with open(r"{outside}", "w") as f:
        f.write("x")


def test_cannot_read_the_env_file(page):
    open(r"{env}").read()


def test_cannot_open_other_websites(page):
    page.goto("https://example.org/")
    assert "example.org" not in page.url


def test_cannot_reach_metadata(page):
    page.request.get("http://169.254.169.254/latest/meta-data")


def test_cannot_send_data(page):
    page.request.post(URL + "/contact", data={{"name": "x"}})


def test_hangs(page):
    while True:
        pass


def test_hangs_and_swallows_every_error(page):
    while True:  # (like a generated "wait until the page settles, else carry on" helper on a slow website)
        try:
            page.wait_for_timeout(200)
        except Exception:
            pass


def test_password_never_in_results(page, qa_login):
    assert False, "the password is " + qa_login[1]
'''


@pytest.fixture(scope="module")
def demo():
    app = DemoApp().start()
    yield app
    app.stop()


def test_sandbox_blocks_escapes_and_reports_honestly(demo, tmp_path, monkeypatch):
    from backend.agents.executor import execution_agent
    from backend.agents.script_generator import TEMPLATES
    run = tmp_path / "run"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    for name in ("conftest.py", "pytest.ini"):
        (tests / name).write_text((TEMPLATES / name).read_text(encoding="utf-8"), encoding="utf-8")
    outside = tmp_path / "outside.txt"
    env_file = Path(".env").resolve()
    (tests / "test_hostile.py").write_text(HOSTILE.format(url=demo.url, outside=outside, env=env_file), encoding="utf-8")
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)
    monkeypatch.setattr(settings, "test_timeout_s", 8)
    monkeypatch.setattr(settings, "test_retries", 1)  # this test asserts retry trace capture; do not inherit machine config
    monkeypatch.setenv("TEST_USERNAME", "demo")
    monkeypatch.setenv("TEST_PASSWORD", "Very$ecret-123")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaFAKEKEY-must-not-reach-tests")

    out = execution_agent({"run_dir": str(run), "url": demo.url, "crawl": {"approved_hosts": ["127.0.0.1"]}, "log": []})
    r = {x["test"]: x for x in out["results"]}

    assert r["test_ok"]["outcome"] == "passed" and r["test_ok"]["checks"] >= 1
    assert r["test_checks_nothing"]["outcome"] == "inconclusive"
    for name in ("test_cannot_start_programs", "test_cannot_write_outside_the_run", "test_cannot_read_the_env_file",
                 "test_cannot_reach_metadata", "test_cannot_send_data"):
        assert r[name]["outcome"] == "failed" and "blocked by the test sandbox" in r[name]["error"], (name, r[name]["error"])
    assert not outside.exists()
    assert r["test_cannot_open_other_websites"]["outcome"] in ("passed", "failed")  # the navigation never got there
    assert "example.org" not in (r["test_cannot_open_other_websites"].get("url") or "")
    assert r["test_hangs"]["outcome"] == "failed" and "TestTimeout" in r["test_hangs"]["error"]
    # (was: the time limit was an Exception - a test's own `except Exception` swallowed it and ran on for ever)
    swallow = r["test_hangs_and_swallows_every_error"]
    assert swallow["outcome"] == "failed" and "TestTimeout" in swallow["error"] and swallow["duration_s"] < 30, swallow
    assert r["test_ok"]["outcome"] == "passed"  # the next tests still ran after the timeout
    text = (run / "results.json").read_text(encoding="utf-8")
    assert "Very$ecret-123" not in text and "[REDACTED]" in text
    assert r["test_password_never_in_results"]["trace"]  # failure evidence: a trace ...
    trace = run / r["test_password_never_in_results"]["trace"]
    assert trace.exists() and b"Very$ecret-123" not in trace.read_bytes()  # ... without the password
    assert json.loads((run / "execution.json").read_text())["timed_out"] is False


def test_watching_shows_every_test_in_one_window_one_after_another(demo, tmp_path, monkeypatch, capsys):
    """Nov 3, 2026: 2 windows plus small checks hidden at the same time - 'some tests run first, some last, I don't
    know how'. Watching now shows EVERY test in ONE window, one after another (journeys first, small checks last)."""
    from backend.agents import executor
    from backend.agents.script_generator import TEMPLATES
    run = tmp_path / "run"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    for name in ("conftest.py", "pytest.ini"):
        (tests / name).write_text((TEMPLATES / name).read_text(encoding="utf-8"), encoding="utf-8")
    one = 'from playwright.sync_api import expect\n\n\ndef test_{n}(page):\n    page.goto("{url}")\n' \
          '    expect(page).to_have_title("Home - DemoShop")\n'
    (tests / "test_journeys.py").write_text(one.format(n="journey", url=demo.url), encoding="utf-8")
    (tests / "test_site.py").write_text(one.format(n="small_check", url=demo.url), encoding="utf-8")
    monkeypatch.setattr(settings, "headless", False)  # "watch in Chrome" ...
    monkeypatch.setattr(settings, "test_workers", 4)
    assert executor._workers(None) == 1  # (one window - never browsers side by side)
    real_env = executor._env
    monkeypatch.setattr(executor, "_env", lambda *a: dict(real_env(*a), HEADLESS="true"))  # (... without a window here)
    out = executor.execution_agent({"run_dir": str(run), "url": demo.url, "crawl": {"approved_hosts": ["127.0.0.1"]},
                                    "log": []})
    assert [(r["test"], r["outcome"]) for r in out["results"]] == [("test_journey", "passed"),
                                                                  ("test_small_check", "passed")]  # (in this order)
    assert not list(run.glob("results_bg*")) and "running tests in" not in capsys.readouterr().out  # (nothing hidden)


ITEM_CODE = '''
import re
from playwright.sync_api import expect

URL = "{url}"


def test_saved_item_is_gone(page):
    page.goto(URL + "/signin")
    page.fill("#email", "{email}")
    page.click("#continue")
    page.fill("#password", "{password}")
    page.click("#signin")
    page.wait_for_load_state()
    page.goto(URL + "/product/999")  # (the website rebuilt its data: the item the crawler saved is gone)
    expect(page).to_have_url(re.compile(r"/product/\\d+$"))
    expect(page.locator(".price")).to_be_visible()
'''


def test_a_saved_item_page_that_is_gone_is_replaced_by_a_current_one(tmp_path, monkeypatch):
    """Demo shops rebuild their data (new ids) every few minutes: the test opens a current item from the list."""
    from backend.agents.executor import execution_agent
    from backend.agents.script_generator import TEMPLATES
    from tests.demo_store import EMAIL, PASSWORD, DemoStore
    store = DemoStore().start()
    try:
        run = tmp_path / "run"
        tests = run / "generated_tests"
        tests.mkdir(parents=True)
        for name in ("conftest.py", "pytest.ini"):
            (tests / name).write_text((TEMPLATES / name).read_text(encoding="utf-8"), encoding="utf-8")
        (tests / "test_items.py").write_text(ITEM_CODE.format(url=store.url, email=EMAIL, password=PASSWORD),
                                             encoding="utf-8")
        monkeypatch.setattr(settings, "headless", True)
        app_map = [{"url": store.url + "/shop", "itemLinks": {"links": [{"href": f"{store.url}/product/{n}"}
                                                                        for n in (1, 2, 3)]}}]
        out = execution_agent({"run_dir": str(run), "url": store.url, "app_map": app_map, "log": [],
                               "crawl": {"approved_hosts": ["127.0.0.1"]}})
        assert out["results"][0]["outcome"] == "passed", out["results"][0].get("error")
    finally:
        store.stop()


AI_CODE = '''
from playwright.sync_api import expect

URL = "{url}"


def test_ai_flow_1(page):
    page.goto(URL)
    expect(page).to_have_title("Home - DemoShop")
    page.get_by_text("Delete all data").click()


def test_ai_flow_2(page):
    page.goto(URL)
    page.click("a[href='/delete-all']")


def test_ai_flow_3(page):
    page.goto(URL)
    page.get_by_text("Delete all data").press("Enter")


def test_ai_flow_4(page):
    page.goto(URL + "/about")
    page.get_by_role("tab", name="Team").click()
    expect(page.locator("#team")).to_be_visible()
'''


def test_ai_written_code_can_never_click_a_protected_action(demo, tmp_path, monkeypatch):
    """The AI is told never to click delete / pay / log out; the sandbox makes sure: the step is Blocked."""
    from backend.agents.executor import execution_agent
    from backend.agents.script_generator import TEMPLATES
    from backend.excel import case_result
    run = tmp_path / "run"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    for name in ("conftest.py", "pytest.ini"):
        (tests / name).write_text((TEMPLATES / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tests / "test_flows_ai.py").write_text(AI_CODE.format(url=demo.url), encoding="utf-8")
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)
    out = execution_agent({"run_dir": str(run), "url": demo.url, "crawl": {"approved_hosts": ["127.0.0.1"]}, "log": []})
    r = {x["test"]: x for x in out["results"]}
    for name in ("test_ai_flow_1", "test_ai_flow_2", "test_ai_flow_3"):
        assert r[name]["outcome"] == "skipped" and r[name]["error"].startswith("Blocked: 'Delete all data'"), r[name]
    assert r["test_ai_flow_4"]["outcome"] == "passed"  # ordinary clicks still work
    assert not any("/delete-all" in v for v in demo.visited)
    case = {"id": "ai_flow_1", "files": ["test_flows_ai.py"], "tests": ["test_ai_flow_1"]}
    assert case_result(case, out["results"])[0] == "Blocked"
