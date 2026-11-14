"""Real Appium Python transport + generated pytest against a local W3C fixture, not an Android emulator."""

import base64
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from backend import android_pipeline
from backend.android import validate_mobile_config
from backend.graph import build_graph

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlS8AAAAASUVORK5CYII="


class AppiumFixture:
    def __init__(self, buggy, disconnect_after=None):
        self.buggy, self.sessions, self.clicked = buggy, {}, []
        self.execution_source_reads = 0
        self.sensitive_headers = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.respond("GET")

            def do_POST(self):
                self.respond("POST")

            def do_DELETE(self):
                self.respond("DELETE")

            def respond(self, method):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or "{}")
                parts = urlparse(self.path).path.strip("/").split("/")
                if parts[0] == 'session':
                    fixture.sensitive_headers.append(self.headers.get('X-Appium-Is-Sensitive'))
                value = None
                if parts == ["session"] and method == "POST":
                    sid = str(len(fixture.sessions) + 1)
                    fixture.sessions[sid] = "Home"
                    value = {
                        "sessionId": sid,
                        "capabilities": {
                            "platformName": "Android",
                            "platformVersion": "36",
                            "automationName": "UiAutomator2",
                        },
                    }
                elif len(parts) >= 2 and parts[0] == "session":
                    sid = parts[1]
                    screen = fixture.sessions[sid]
                    command = "/".join(parts[2:])
                    controls = fixture.controls(screen)
                    if command == "execute/sync":
                        script = body.get("script")
                        if script in ("mobile: startActivity", "mobile: activateApp", "mobile: terminateApp"):
                            fixture.sessions[sid] = "Home"
                        value = (
                            "com.blowai.protocol"
                            if script == "mobile: getCurrentPackage"
                            else ".MainActivity"
                            if script == "mobile: getCurrentActivity"
                            else None
                        )
                    elif command == "appium/device/current_package":
                        value = "com.blowai.protocol"
                    elif command == "appium/device/current_activity":
                        value = ".MainActivity"
                    elif command == "source":
                        if sid == "2" and disconnect_after is not None:
                            fixture.execution_source_reads += 1
                            if fixture.execution_source_reads > disconnect_after:
                                data = json.dumps({"value": {"error": "unknown error", "message":
                                    "adb.exe: device 'protocol-fixture' not found"}}).encode()
                                self.send_response(500)
                                self.send_header("Content-Type", "application/json")
                                self.send_header("Content-Length", str(len(data)))
                                self.end_headers()
                                self.wfile.write(data)
                                return
                        value = fixture.xml(screen)
                    elif command == "screenshot":
                        value = PNG
                    elif command == "back":
                        fixture.sessions[sid] = "Home"
                    elif command == "elements":
                        using, target = body["using"], body["value"]
                        if using == "-android uiautomator":
                            match = re.search(r"text\((.*)\)", target)
                            target = json.loads(match.group(1)) if match else target
                        value = [
                            {"element-6066-11e4-a52e-4f735466cecf": key}
                            for key, label in controls.items()
                            if target in (label, "com.blowai.protocol:id/" + key)
                        ]
                    elif command.startswith("element/"):
                        key, operation = parts[3], parts[4]
                        if operation in ("displayed", "enabled"):
                            value = key in controls
                        elif operation == "text":
                            value = controls[key]
                        elif operation == "click":
                            label = controls[key]
                            fixture.clicked.append(label)
                            fixture.sessions[sid] = "Settings" if label == "About" and fixture.buggy else label
                data = json.dumps({"value": value}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def controls(self, screen):
        if screen == "Home":
            return {"title": "Home", "settings": "Settings", "about": "About"}
        return {"title": screen, "home": "Home", "delete": "Delete account"}

    def xml(self, screen):
        nodes = []
        for key, label in self.controls(screen).items():
            kind = "TextView" if key == "title" else "Button"
            nodes.append(
                f'<node class="android.widget.{kind}" resource-id="com.blowai.protocol:id/{key}" '
                f'content-desc="{label}" text="{label}" enabled="true" displayed="true" clickable="{str(key != "title").lower()}"/>'
            )
        return "<hierarchy>" + "".join(nodes) + "</hierarchy>"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.mark.parametrize("buggy,expected", [(False, "Ready with Risks"), (True, "Not Ready")])
def test_mobile_generated_pipeline_with_real_pytest_and_mock_appium_transport(tmp_path, monkeypatch, buggy, expected):
    with AppiumFixture(buggy) as fixture:
        config = validate_mobile_config(
            {
                "app_mode": "installed",
                "package_name": "com.blowai.protocol",
                "device_id": "protocol-fixture",
                "appium_url": f"http://127.0.0.1:{fixture.server.server_port}",
                "max_screens": 5,
                "max_actions": 30,
                "max_depth": 2,
                "expected_destinations": {"settings": "Settings", "about": "About", "home": "Home"},
            }
        )
        private = tmp_path / ".private"
        private.mkdir()
        (private / "android_config.json").write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(
            android_pipeline,
            "android_environment",
            lambda _url: {"ok": True, "errors": [], "devices": [{"device_id": "protocol-fixture", "status": "device"}]},
        )
        with SqliteSaver.from_conn_string(str(private / "checkpoint.sqlite")) as saver:
            graph = build_graph(checkpointer=saver, target_type="mobile")
            thread = {"configurable": {"thread_id": "protocol-test"}}
            final = graph.invoke(
                {
                    "target_type": "mobile",
                    "config": config,
                    "run_dir": str(tmp_path),
                    "run_id": "protocol-test",
                    "log": [],
                },
                thread,
            )
            assert graph.get_state(thread).values["results"]
            assert not graph.get_state(thread).next
        assert final["verdict"] == expected, final
        results = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
        assert any(r["outcome"] == "passed" and r.get("checks", 0) > 0 for r in results)
        assert any(r["outcome"] == "blocked" for r in results)
        assert "Delete account" not in fixture.clicked
        assert (tmp_path / "test_cases.xlsx").is_file()
        assert (tmp_path / "report.html").is_file()
        assert len(final["screens"]) >= 2
        assert fixture.sensitive_headers and set(fixture.sensitive_headers) == {'1'}
        if buggy:
            failed = next(r for r in results if r["outcome"] == "failed")
            assert failed["exception_type"] == "AssertionError"
            shot = tmp_path / failed["screenshot"]
            assert shot.read_bytes() == base64.b64decode(PNG)
            failures = json.loads((tmp_path / "failures.json").read_text(encoding="utf-8"))
            assert any(f["category"] == "assertion_failure" for f in failures)


def test_device_loss_records_one_error_and_blocks_remaining_cases(tmp_path, monkeypatch):
    from backend import llm
    monkeypatch.setattr(llm.settings, "llm_provider", "none")
    with AppiumFixture(False, disconnect_after=10) as fixture:
        config = validate_mobile_config({"app_mode": "installed", "package_name": "com.blowai.protocol",
            "device_id": "protocol-fixture", "appium_url": f"http://127.0.0.1:{fixture.server.server_port}",
            "max_screens": 3, "max_actions": 8, "max_depth": 1})
        private = tmp_path / ".private"
        private.mkdir()
        (private / "android_config.json").write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(android_pipeline, "android_environment", lambda _: {
            "ok": True, "errors": [], "devices": [{"device_id": "protocol-fixture", "status": "device"}]})
        state = {"config": config, "run_id": "disconnect-fixture", "run_dir": str(tmp_path), "log": []}
        state.update(android_pipeline.discovery_agent(state))
        state.update(android_pipeline.test_design_agent(state))
        state.update(android_pipeline.script_generator_agent(state))
        state.update(android_pipeline.execution_agent(state))
        errors = [r for r in state["results"] if r["outcome"] == "error"]
        assert len(errors) == 1, errors
        assert any(r["outcome"] == "blocked" and "Not executed" in r.get("error", "") for r in state["results"])
        assert state["incomplete"] and "device/session loss" in state["incomplete_reason"]
        assert fixture.sensitive_headers and set(fixture.sensitive_headers) == {'1'}
