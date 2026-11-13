"""Offline Appium autostart, readiness and preparation API regressions."""
import subprocess

import pytest
from fastapi.testclient import TestClient

from backend import android, android_emulator as emu, android_service as service, server
from tests.test_android_api import DEVICE_ENVIRONMENT, HEADERS

URL = "http://127.0.0.1:4723"


@pytest.fixture
def startup(monkeypatch, tmp_path):
    state = {"ready": False, "exit": None, "launches": [], "auto_ready": True}

    class Process:
        def poll(self):
            return state["exit"]

    def launch(command, **kwargs):
        state["launches"].append((command, kwargs))
        if state["auto_ready"]:
            state["ready"] = True
        return Process()

    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service, "_launches", {})
    monkeypatch.setattr(service, "_ready", lambda url: state["ready"])
    monkeypatch.setattr(service, "_listening", lambda *args: False)
    monkeypatch.setattr(service, "_appium_path", lambda: "appium")
    monkeypatch.setattr(service, "_sdk_path", lambda: str(tmp_path / "sdk"))
    monkeypatch.setattr(service, "_java_path", lambda: str(tmp_path / "jdk/bin/java.exe"))
    monkeypatch.setattr(service, "_command", lambda program: [program])
    monkeypatch.setattr(service.subprocess, "Popen", launch)
    return state


def test_appium_launch_waits_until_ready_and_reuses_existing_server(startup):
    assert service.ensure_appium_ready(URL) == {"url": URL, "started": True}
    assert service.ensure_appium_ready(URL) == {"url": URL, "started": False}
    assert len(startup["launches"]) == 1
    command, options = startup["launches"][0]
    assert command == ["appium", "--address", "127.0.0.1", "--port", "4723", "--base-path", "/", "--log-level", "warn"]
    assert options["stdin"] == subprocess.DEVNULL and not options.get("shell")
    assert options["env"]["ANDROID_HOME"].endswith("sdk")
    assert options["env"]["JAVA_HOME"].endswith("jdk")
    if service.os.name == "nt":
        assert options["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_running_server_is_not_replaced(startup):
    startup["ready"] = True
    assert not service.ensure_appium_ready(URL)["started"]
    assert not startup["launches"]


def test_slow_start_retry_waits_for_the_same_process(startup):
    startup["auto_ready"] = False
    for _ in range(2):
        with pytest.raises(android.AndroidEnvironmentError, match="did not become ready"):
            service.ensure_appium_ready(URL, timeout_s=0)
    assert len(startup["launches"]) == 1
    startup["ready"] = True
    assert not service.ensure_appium_ready(URL)["started"]


def test_occupied_port_never_launches_another_server(startup, monkeypatch):
    monkeypatch.setattr(service, "_listening", lambda *args: True)
    with pytest.raises(android.AndroidEnvironmentError, match="another program is using port 4723"):
        service.ensure_appium_ready(URL, timeout_s=0)
    assert not startup["launches"]


def test_process_exits_reports_log_instead_of_creating_a_test(startup):
    startup.update(auto_ready=False, exit=1)
    with pytest.raises(android.AndroidEnvironmentError, match="Appium exited during startup"):
        service.ensure_appium_ready(URL)


@pytest.mark.parametrize("url", ["http://example.com:4723", "http://user:secret@localhost:4723",
                                 "http://localhost:bad", "http://localhost:4723?x=1", "http://localhost:0"])
def test_invalid_or_remote_appium_urls_never_launch(startup, url):
    with pytest.raises(android.AndroidEnvironmentError):
        service.ensure_appium_ready(url)
    assert not startup["launches"]


def test_https_autostart_requires_explicit_local_http_url(startup):
    with pytest.raises(android.AndroidEnvironmentError, match="Automatic Appium startup uses HTTP"):
        service.ensure_appium_ready("https://localhost:4723")
    assert not startup["launches"]


def test_configured_port_and_base_path_are_passed_without_a_shell(startup):
    service.ensure_appium_ready("http://localhost:4730/wd/hub")
    command = startup["launches"][0][0]
    assert command[command.index("--address") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "4730"
    assert command[command.index("--base-path") + 1] == "/wd/hub"


def test_missing_appium_is_actionable(startup, monkeypatch):
    monkeypatch.setattr(service, "_appium_path", lambda: None)
    with pytest.raises(android.AndroidEnvironmentError, match="Appium is not installed"):
        service.ensure_appium_ready(URL)
    assert not startup["launches"]


@pytest.mark.skipif(service.os.name != "nt", reason="Windows npm entrypoint")
@pytest.mark.parametrize("local_install", [False, True])
def test_windows_npm_shim_uses_node_without_cmd(tmp_path, monkeypatch, local_install):
    shim_dir = tmp_path / "with spaces & symbols" / ("node_modules/.bin" if local_install else "npm")
    shim_dir.mkdir(parents=True)
    entry = (shim_dir.parent / "appium" if local_install else shim_dir / "node_modules/appium") / "build/lib/main.js"
    entry.parent.mkdir(parents=True)
    entry.touch()
    monkeypatch.setattr(service.shutil, "which", lambda name: "node.exe")
    assert service._command(str(shim_dir / "appium.cmd")) == ["node.exe", str(entry)]


@pytest.fixture
def preparation(monkeypatch):
    environment = {**DEVICE_ENVIRONMENT, "ok": False, "devices": [], "appium": {"available": False},
                   "errors": ["Appium server is not running at " + URL, "No Android device is connected."]}
    actions = []
    monkeypatch.setattr(server, "jobs", {})
    monkeypatch.setattr(android, "android_environment", lambda *_: environment)
    monkeypatch.setattr(emu, "list_emulators", lambda *_: [{"name": "demo", "device_id": "avd:demo"}])

    def appium(*_):
        actions.append("appium")
        return {"url": URL, "started": True}

    def device(*_):
        actions.append("device")
        return {"device_id": "emulator-5554", "started": True, "avd_name": "demo"}

    monkeypatch.setattr(service, "ensure_appium_ready", appium)
    monkeypatch.setattr(emu, "ensure_device_ready", device)
    return environment, actions


def test_environment_refresh_allows_stopped_tools_without_starting_them(preparation):
    _, actions = preparation
    with TestClient(server.app, base_url="http://127.0.0.1:8000") as client:
        result = client.get("/api/android/environment").json()
    assert result["can_prepare"] and result["can_start_emulator"] and not result["ok"]
    assert not actions


@pytest.mark.parametrize("stage,expected", [("all", ["appium", "device"]), ("appium", ["appium"]),
                                           ("device", ["appium", "device"])])
def test_prepare_starts_appium_before_booting_device(preparation, stage, expected):
    _, actions = preparation
    with TestClient(server.app, base_url="http://127.0.0.1:8000") as client:
        result = client.post("/api/android/prepare", headers=HEADERS,
                             json={"device_id": "avd:demo", "authorized": True, "stage": stage})
    assert result.status_code == 200, result.text
    assert actions == expected and not server.jobs


def test_stopped_appium_with_a_connected_phone_can_be_prepared(preparation, monkeypatch):
    environment, _ = preparation
    environment["devices"] = [{"device_id": "phone", "status": "device"}]
    environment["errors"] = environment["errors"][:1]
    monkeypatch.setattr(emu, "list_emulators", lambda *_: [])
    assert emu.startup_choices(environment)["can_prepare"]


@pytest.mark.parametrize("problem", ["Java is too old.", "UiAutomator2 driver is not installed.", "ADB device query failed."])
def test_missing_prerequisites_block_startup(preparation, problem):
    environment, actions = preparation
    environment["errors"].append(problem)
    assert not emu.startup_choices(environment)["can_prepare"]
    with TestClient(server.app, base_url="http://127.0.0.1:8000") as client:
        result = client.post("/api/android/prepare", headers=HEADERS,
                             json={"device_id": "avd:demo", "authorized": True})
    assert result.status_code == 409 and problem in result.json()["detail"]
    assert not actions


def test_appium_failure_prevents_emulator_start(preparation, monkeypatch):
    _, actions = preparation

    def fail(*_):
        raise android.AndroidEnvironmentError("Appium exited during startup.")

    monkeypatch.setattr(service, "ensure_appium_ready", fail)
    with TestClient(server.app, base_url="http://127.0.0.1:8000") as client:
        result = client.post("/api/android/prepare", headers=HEADERS,
                             json={"device_id": "avd:demo", "authorized": True})
    assert result.status_code == 409 and "Appium exited" in result.json()["detail"]
    assert not actions
