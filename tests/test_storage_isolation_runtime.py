"""Each generated test starts from the same web storage (the saved login's, or nothing for a guest): the live hybrid
SauceDemo run (26 Nov) had built-in 'Add to cart' tests fail because an earlier test's cart, kept in localStorage,
was still there ('Remove' instead of 'Add to cart'). Real Chromium, the real generated-test conftest."""
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HITS = []
SHOP = b"""<html><head><title>Shop</title></head><body><button id="add">Add to cart</button><span id="badge"></span>
<script>
const show = () => { const n = JSON.parse(localStorage.getItem('cart') || '[]').length;
  document.getElementById('badge').textContent = n ? String(n) : '';
  document.getElementById('add').textContent = n ? 'Remove' : 'Add to cart'; };
document.getElementById('add').onclick = () => { localStorage.setItem('cart', '[4]'); show(); };
show();
</script></body></html>"""

TESTS = '''from playwright.sync_api import expect


def test_a_adds(page):
    page.goto(BASE)
    expect(page.locator("#add")).to_have_text("Add to cart")
    page.click("#add")
    expect(page.locator("#badge")).to_have_text("1")


def test_b_starts_clean_but_logged_in(page):
    page.goto(BASE)
    expect(page.locator("#add")).to_have_text("Add to cart")
    assert page.evaluate("localStorage.getItem('session-user')") == "standard_user"
    assert page.evaluate("localStorage.getItem('cart')") is None
'''


class Shop(SimpleHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(SHOP)

    def log_message(self, *a):
        pass


@pytest.fixture
def site():
    srv = HTTPServer(("127.0.0.1", 0), Shop)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_an_earlier_tests_web_storage_never_reaches_the_next_test(tmp_path, site):
    tests = tmp_path / "generated_tests"
    tests.mkdir()
    shutil.copy(ROOT / "backend" / "templates" / "conftest.py", tests / "conftest.py")
    shutil.copy(ROOT / "backend" / "templates" / "pytest.ini", tests / "pytest.ini")
    (tests / "test_shop.py").write_text(TESTS.replace("BASE", repr(site + "/")))
    auth = tmp_path / "auth.json"  # (the crawler's saved login: a cookie and its own localStorage key)
    auth.write_text(json.dumps({"cookies": [], "origins": [
        {"origin": site, "localStorage": [{"name": "session-user", "value": "standard_user"}]}]}))
    results = tmp_path / "results.jsonl"
    env = {**{k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_XDIST", "PYTEST_CURRENT"))},
           "QA_RESULTS_FILE": str(results), "QA_RUN_DIR": str(tmp_path), "QA_BASE_URL": site + "/",
           "QA_AUTH_STATE": str(auth), "QA_TARGET_LOCAL": "1", "QA_ALLOWED_HOSTS": "127.0.0.1",
           "QA_LIVE_FRAMES": "false", "QA_TRACES": "false", "QA_SCREENSHOT_DIR": str(tmp_path / "s"), "PYTHONPATH": ""}
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "."],
                         cwd=tests, env=env, capture_output=True, text=True, timeout=300)
    got = {json.loads(ln)["test"]: json.loads(ln) for ln in results.read_text().splitlines()}
    assert got["test_a_adds"]["outcome"] == "passed", out.stdout[-2000:]
    assert got["test_b_starts_clean_but_logged_in"]["outcome"] == "passed", got["test_b_starts_clean_but_logged_in"]
    assert not [h for h in HITS if "__qa_storage_reset__" in h]  # (the website itself is never asked for it)
