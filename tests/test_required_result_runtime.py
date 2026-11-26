"""A Jira / owner test passes only when the result its test case QUOTES was really checked while it ran.
Generation already refuses code that never mentions the quoted result (script_generator.quoted_expectations); this
covers the runtime gap: a check placed in a branch that is not taken, or in a helper never called, used to let the test
pass on its other checks. Real Chromium, the real generated-test conftest (backend/templates/conftest.py)."""
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

from backend.agents.script_generator import with_required_results

ROOT = Path(__file__).resolve().parent.parent
PAGE = b"<html><head><title>Shop</title></head><body><h1>Checkout complete</h1><p>Thank you for your order!</p></body></html>"

TESTS = '''import re
import pytest
from playwright.sync_api import expect


def test_tc_1(page):  # checks the quoted result: passes
    page.goto(BASE)
    expect(page).to_have_title("Shop")
    expect(page.locator("body")).to_contain_text("Thank you for your order!")


def test_tc_2(page):  # the quoted check sits in a branch that is not taken: NOT a pass
    page.goto(BASE)
    expect(page).to_have_title("Shop")
    if page.locator("#never").count():
        expect(page.locator("body")).to_contain_text("Thank you for your order!")


def test_tc_3(page):  # checked with a plain assert on the text read: passes
    page.goto(BASE)
    body = page.locator("body").inner_text()
    assert "Thank you for your order!" in body


def test_tc_4(page):  # checked through a variable: passes (the compared value is recorded)
    page.goto(BASE)
    wanted = "Thank you for your order!"
    expect(page.locator("p")).to_have_text(wanted)


def test_tc_5(page):  # the quoted result is not on the page: fails as usual
    page.goto(BASE)
    expect(page.locator("body")).to_contain_text("Order cancelled", timeout=1500)
'''


class Quiet(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *a):
        pass


@pytest.fixture
def site():
    srv = HTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/"
    srv.shutdown()


def test_a_pass_needs_the_quoted_result_checked_while_the_test_ran(tmp_path, site):
    flows = [{"id": f"tc_{n}", "my_test": True, "expected": "The page shows 'Thank you for your order!'"}
             for n in range(1, 5)] + [{"id": "tc_5", "my_test": True, "expected": "It shows 'Order cancelled'"}]
    code = with_required_results(TESTS.replace("BASE", repr(site)), flows)
    assert "QA_EXPECTS_test_tc_2 = ['Thank you for your order!']" in code
    tests = tmp_path / "generated_tests"
    tests.mkdir()
    shutil.copy(ROOT / "backend" / "templates" / "conftest.py", tests / "conftest.py")
    shutil.copy(ROOT / "backend" / "templates" / "pytest.ini", tests / "pytest.ini")
    (tests / "test_flows_ai.py").write_text(code)
    results = tmp_path / "results.jsonl"
    env = {**os.environ, "QA_RESULTS_FILE": str(results), "QA_RUN_DIR": str(tmp_path), "QA_BASE_URL": site,
           "QA_TARGET_LOCAL": "1", "QA_ALLOWED_HOSTS": "127.0.0.1", "QA_LIVE_FRAMES": "false", "QA_TRACES": "false",
           "QA_SCREENSHOT_DIR": str(tmp_path / "shots"), "PYTHONPATH": ""}
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "."],
                   cwd=tests, env=env, capture_output=True, text=True, timeout=300)
    got = {json.loads(ln)["test"]: json.loads(ln) for ln in results.read_text().splitlines()}
    assert got["test_tc_1"]["outcome"] == "passed"
    assert got["test_tc_2"]["outcome"] == "inconclusive" and "never checked" in got["test_tc_2"]["error"]
    assert got["test_tc_3"]["outcome"] == "passed"
    assert got["test_tc_4"]["outcome"] == "passed"
    assert got["test_tc_5"]["outcome"] == "failed"
