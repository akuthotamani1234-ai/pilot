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
