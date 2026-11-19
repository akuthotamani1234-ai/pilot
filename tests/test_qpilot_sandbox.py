"""Exercise the generated-test sandbox against a controlled local page, including durable events."""
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend.agents.executor import _read, _run_pytest
from backend.config import settings
from backend.execution_events import read_events
from backend.form_targets import FORM_TARGET_HELPER


@pytest.mark.slow
def test_real_sandbox_records_actions_and_redacts_password(tmp_path, monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b'<title>Controlled fixture</title><aside><input id=sidebar></aside>'
                            b'<form id=contact><label for=password>Password</label><input id=password type=password></form>')

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    test_dir = tmp_path / "generated_tests"
    test_dir.mkdir()
    templates = Path(__file__).resolve().parents[1] / "backend" / "templates"
    for name in ("conftest.py", "pytest.ini"):
        shutil.copy2(templates / name, test_dir / name)
    secret = "Fixture-Secret-1234"
    monkeypatch.setattr(settings, "test_password", secret)
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)
    monkeypatch.setattr(settings, "test_timeout_s", 30)
    spec = {"form": "#contact", "fields": [{"selector": "#password", "label": "Password", "name": "Password",
                                            "kind": "type", "value": secret, "required": True}]}
    code = "from playwright.sync_api import expect\n" + FORM_TARGET_HELPER + f'''
def test_input(page):
    page.goto({url!r})
    fill_input_check(page, {spec!r})
    assert page.locator('#sidebar').input_value() == ''
'''
    (test_dir / "test_fixture.py").write_text(code, encoding="utf-8")
    try:
        info = _run_pytest({"url": url, "run_dir": str(tmp_path)}, test_dir, tmp_path / "results.jsonl", tmp_path / "shots")
    finally:
        server.shutdown()
        server.server_close()
    assert info["returncode"] == 0, (tmp_path / "results_pytest_output.txt").read_text(encoding="utf-8")
    assert _read(tmp_path / "results.jsonl")[0]["outcome"] == "passed"
    events = read_events(tmp_path, limit=500)["events"]
    assert any(e["status"] == "running" and "Type" in e["text"] for e in events)
    assert any(e["status"] == "passed" for e in events)
    assert secret not in json.dumps(events)


def test_a_test_suite_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    secret = b"tenant-b-only-suite"
    other = tmp_path / "other"
    other.mkdir()
    (other / "results.jsonl").write_bytes(secret)
    (other / "results_junit.xml").write_bytes(secret)
    (other / "results_pytest_output.txt").write_bytes(secret)
    run = tmp_path / "run"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    (run / "results.jsonl").symlink_to(other / "results.jsonl")
    (run / "results_junit.xml").symlink_to(other / "results_junit.xml")
    (run / "results_pytest_output.txt").symlink_to(other / "results_pytest_output.txt")

    def explode(*_args, **_kwargs):
        raise AssertionError("started")

    monkeypatch.setattr("backend.agents.executor.subprocess.Popen", explode)
    info = _run_pytest({}, tests, run / "results.jsonl", run / "screenshots")
    assert info["stopped"] is True and info["returncode"] == -1
    assert (other / "results.jsonl").read_bytes() == secret
    assert (other / "results_junit.xml").read_bytes() == secret
    assert (other / "results_pytest_output.txt").read_bytes() == secret

    (other / "traces").mkdir()
    (other / "videos").mkdir()
    (other / "auth.json").write_bytes(secret)
    (other / "role.json").write_bytes(secret)
    (other / "keep.txt").write_bytes(secret)
    fresh = tmp_path / "fresh"
    tests = fresh / "generated_tests"
    tests.mkdir(parents=True)
    (fresh / "traces").symlink_to(other / "traces", target_is_directory=True)
    info = _run_pytest({}, tests, fresh / "results.jsonl", fresh / "screenshots")
    assert info["stopped"] is True and info["returncode"] == -1
    (fresh / "traces").unlink()
    (fresh / "videos").symlink_to(other / "videos", target_is_directory=True)
    monkeypatch.setattr(settings, "record_video", True)
    info = _run_pytest({}, tests, fresh / "results.jsonl", fresh / "screenshots")
    assert info["stopped"] is True
    (fresh / "videos").unlink()
    private = fresh / ".private"
    private.mkdir()
    (private / "auth.json").symlink_to(other / "auth.json")
    info = _run_pytest({}, tests, fresh / "results.jsonl", fresh / "screenshots")
    assert info["stopped"] is True
    (private / "auth.json").unlink()
    (private / "role.json").symlink_to(other / "role.json")
    info = _run_pytest({"roles": {"roles": {"shopper": {"state": "role.json"}}}}, tests,
                       fresh / "results.jsonl", fresh / "screenshots")
    assert info["stopped"] is True
    assert (other / "auth.json").read_bytes() == secret
    assert (other / "role.json").read_bytes() == secret
    assert (other / "keep.txt").read_bytes() == secret
    assert list((other / "traces").iterdir()) == []
    assert list((other / "videos").iterdir()) == []

    owned = tmp_path / "owned"
    (owned / "generated_tests").mkdir(parents=True)
    from backend.agents.executor import _env
    env = _env(owned, owned / "generated_tests", owned / "results.jsonl", owned / "screenshots", {})
    assert Path(env["QA_RUN_DIR"]) == owned.resolve()
    assert secret.decode() not in env["QA_RUN_DIR"]
