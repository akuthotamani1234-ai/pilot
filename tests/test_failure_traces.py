"""A failing test keeps a Playwright trace from its first run (not only on a retry); a passing test keeps none."""
import http.server
import shutil
import threading
import zipfile

from backend.config import settings


def _serve():
    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = b"<title>Shop</title><h1>Shop</h1><button>Buy</button>"
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


def _suite(tmp_path, url):
    from backend.agents.script_generator import TEMPLATES
    run = tmp_path / "run1"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    shutil.copy(TEMPLATES / "conftest.py", tests / "conftest.py")
    shutil.copy(TEMPLATES / "pytest.ini", tests / "pytest.ini")
    (tests / "test_shop.py").write_text(
        "from playwright.sync_api import expect\n\n\n"
        f"def test_title_is_shop(page):\n    page.goto({url + '/'!r})\n    expect(page.locator('h1')).to_have_text('Shop')\n\n\n"
        f"def test_title_is_wrong(page):\n    page.goto({url + '/'!r})\n"
        "    expect(page.locator('h1')).to_have_text('Not the shop', timeout=1000)\n", encoding="utf-8")
    return run, tests


def test_first_run_keeps_a_trace_for_each_failing_test_only(tmp_path, monkeypatch):
    from backend.agents.executor import _read, _run_pytest
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)
    assert settings.trace_failures is True  # the default
    srv, url = _serve()
    run, tests = _suite(tmp_path, url)
    try:
        _run_pytest({"url": url + "/", "crawl": {"approved_hosts": ["127.0.0.1"]}, "app_map": [], "login": {}},
                    tests, run / "results.jsonl", run / "shots", traces=settings.trace_failures)
    finally:
        srv.shutdown()
    got = {r["test"]: r for r in _read(run / "results.jsonl")}
    assert got["test_title_is_shop"]["outcome"] == "passed"
    assert got["test_title_is_wrong"]["outcome"] == "failed"
    traces = sorted((run / "traces").glob("*.zip"))
    assert len(traces) == 1 and "wrong" in traces[0].name
    assert got["test_title_is_wrong"].get("trace")
    with zipfile.ZipFile(traces[0]) as z:
        assert any(n.endswith(".trace") for n in z.namelist())


def test_traces_can_be_switched_off(tmp_path, monkeypatch):
    from backend.agents.executor import _run_pytest
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)
    srv, url = _serve()
    run, tests = _suite(tmp_path, url)
    try:
        _run_pytest({"url": url + "/", "crawl": {"approved_hosts": ["127.0.0.1"]}, "app_map": [], "login": {}},
                    tests, run / "results.jsonl", run / "shots", traces=False)
    finally:
        srv.shutdown()
    assert not list((run / "traces").glob("*.zip"))
