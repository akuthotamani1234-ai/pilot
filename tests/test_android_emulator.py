"""Emulator startup, target identity and Start-button sequencing regressions."""
import subprocess

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from backend import android, android_emulator as emu, server
from tests.test_android_api import DEVICE_ENVIRONMENT, HEADERS
from tests.test_results_layout import browser as shared_browser, studio


@pytest.fixture
def harness(monkeypatch, tmp_path):
    state = {"devices": [], "launches": [], "boot": "1", "exit": None}

    class Process:
        def poll(self):
            return state["exit"]

    def launch(sdk, name, serial):
        state["launches"].append((name, serial))
        proc = Process()
        emu._launches[serial] = {"process": proc, "name": name}
        state["devices"] = [{"device_id": serial, "status": "device"}]
        return proc

    monkeypatch.setattr(emu, "_launches", {})
    monkeypatch.setattr(emu, "ROOT", tmp_path)
    monkeypatch.setattr(emu, "_sdk_path", lambda: str(tmp_path))
    monkeypatch.setattr(emu, "_adb_path", lambda: "adb")
    monkeypatch.setattr(emu, "list_emulators", lambda sdk: [{"name": "demo", "device_id": "avd:demo"}])
    monkeypatch.setattr(emu, "connected_avd_name", lambda adb, serial: "demo")
    monkeypatch.setattr(emu, "_devices", lambda adb: state["devices"])
    monkeypatch.setattr(emu, "_port_available", lambda port: True)
    monkeypatch.setattr(emu, "_run_cli", lambda *args: subprocess.CompletedProcess([], 0, state["boot"], ""))
    monkeypatch.setattr(emu, "_launch", launch)
    return state


def test_closed_avd_starts_and_resolves_to_the_real_serial(harness):
    result = emu.ensure_device_ready("avd:demo")
    assert result == {"device_id": "emulator-5554", "avd_name": "demo", "started": True}
    assert harness["launches"] == [("demo", "emulator-5554")]


def test_closed_previous_selection_reopens_the_same_port(harness):
    result = emu.ensure_device_ready("emulator-5556", "demo")
    assert result["device_id"] == "emulator-5556"
    assert harness["launches"] == [("demo", "emulator-5556")]


def test_running_emulator_is_reused_without_another_launch(harness):
    harness["devices"] = [{"device_id": "emulator-5554", "status": "device"}]
    result = emu.ensure_device_ready("avd:demo")
    assert not result["started"]
    assert not harness["launches"]


def test_running_emulator_must_match_the_selected_avd(harness, monkeypatch):
    harness["devices"] = [{"device_id": "emulator-5554", "status": "device"}]
    monkeypatch.setattr(emu, "connected_avd_name", lambda *_: "different")
    with pytest.raises(android.AndroidEnvironmentError, match="does not match"):
        emu.ensure_device_ready("emulator-5554", "demo")
    assert not harness["launches"]


def test_disconnected_phone_is_never_replaced_with_an_emulator(harness):
    with pytest.raises(android.AndroidEnvironmentError, match="phone is disconnected"):
        emu.ensure_device_ready("physical-phone", "demo")
    assert not harness["launches"]


@pytest.mark.parametrize("device,name", [("avd:missing", ""), ("avd:demo;bad", ""),
                                        ("emulator-5555", "demo"), ("emulator-5554", "../outside")])
def test_invalid_or_uninstalled_targets_never_launch(harness, device, name):
    with pytest.raises(android.AndroidEnvironmentError):
        emu.ensure_device_ready(device, name)
    assert not harness["launches"]


def test_boot_timeout_does_not_spawn_a_duplicate_on_retry(harness):
    with pytest.raises(android.AndroidEnvironmentError, match="did not finish booting"):
        emu.ensure_device_ready("avd:demo", timeout_s=0)
    harness["devices"] = []
    with pytest.raises(android.AndroidEnvironmentError, match="did not finish booting"):
        emu.ensure_device_ready("avd:demo", timeout_s=0)
    assert len(harness["launches"]) == 1


def test_unknown_offline_emulator_is_not_started_twice(harness):
    harness["devices"] = [{"device_id": "emulator-5554", "status": "offline"}]
    with pytest.raises(android.AndroidEnvironmentError, match="still connecting"):
        emu.ensure_device_ready("avd:demo")
    assert not harness["launches"]


def test_emulator_process_failure_is_actionable(harness):
    harness["exit"] = 1
    harness["boot"] = "0"
    with pytest.raises(android.AndroidEnvironmentError, match="exited before Android was ready"):
        emu.ensure_device_ready("avd:demo")


def test_startup_options_do_not_hide_missing_java(harness):
    missing = {**DEVICE_ENVIRONMENT, "ok": False, "devices": [],
               "errors": ["No Android device is connected. Start an emulator."]}
    assert emu.startup_choices(missing)["can_start_emulator"]
    missing["errors"].append("Java is too old.")
    assert not emu.startup_choices(missing)["can_start_emulator"]


def test_avd_listing_does_not_start_a_process(tmp_path, monkeypatch):
    binary = tmp_path / "emulator" / ("emulator.exe" if emu.os.name == "nt" else "emulator")
    binary.parent.mkdir()
    binary.touch()
    monkeypatch.setattr(emu, "_run_cli", lambda *args: subprocess.CompletedProcess([], 0, "demo\n\ndemo\nbad;name\n", ""))
    monkeypatch.setattr(emu.subprocess, "Popen", lambda *a, **k: pytest.fail("Listing must not launch Android"))
    assert emu.list_emulators(str(tmp_path)) == [{"name": "demo", "device_id": "avd:demo"}]


def test_launcher_keeps_data_and_uses_structured_arguments(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(emu, "ROOT", tmp_path)
    monkeypatch.setattr(emu, "_launches", {})

    def launch(command, **kwargs):
        captured.update(command=command, **kwargs)
        return object()

    monkeypatch.setattr(emu.subprocess, "Popen", launch)
    emu._launch(str(tmp_path / "sdk"), "demo", "emulator-5554")
    command = captured["command"]
    assert command[command.index("-port") + 1] == "5554"
    assert command[command.index("-avd") + 1] == "demo"
    assert "-wipe-data" not in command and "-no-window" not in command
    assert not captured.get("shell")
    assert captured["env"]["ANDROID_HOME"] == str(tmp_path / "sdk")


def test_prepare_api_requires_permission_and_does_not_create_a_run(harness, monkeypatch):
    monkeypatch.setattr(server, "jobs", {})
    monkeypatch.setattr(android, "android_environment", lambda *_: {
        **DEVICE_ENVIRONMENT, "ok": False, "devices": [],
        "errors": ["No Android device is connected. Start an emulator."]})
    with TestClient(server.app, base_url="http://127.0.0.1:8000") as client:
        denied = client.post("/api/android/prepare", headers=HEADERS, json={"device_id": "avd:demo"})
        assert denied.status_code == 400 and not harness["launches"]
        response = client.post("/api/android/prepare", headers=HEADERS,
                               json={"device_id": "avd:demo", "authorized": True})
    assert response.status_code == 200
    assert response.json()["device_id"] == "emulator-5554"
    assert not server.jobs


def test_prepare_api_does_not_interrupt_an_active_test(harness, monkeypatch):
    monkeypatch.setattr(server, "jobs", {1: {"status": "running"}})
    with TestClient(server.app, base_url="http://127.0.0.1:8000") as client:
        response = client.post("/api/android/prepare", headers=HEADERS,
                               json={"device_id": "avd:demo", "authorized": True})
    assert response.status_code == 409
    assert not harness["launches"]


@pytest.fixture(scope="module")
def browser():
    yield from shared_browser.__wrapped__()


@pytest.mark.parametrize("failure_stage", ["", "appium", "device"])
@pytest.mark.parametrize("previously_connected", [False, True])
def test_start_button_prepares_android_before_submitting_the_test(browser, failure_stage, previously_connected):
    context, page, errors, calls = studio(browser)
    environment = {"ok": False, "devices": [], "can_prepare": True, "appium": {"available": False},
                   "emulators": [{"name": "demo", "device_id": "avd:demo"}],
                   "errors": ["Appium server is not running.", "No Android device is connected."]}
    if previously_connected:
        environment.update(devices=[{"device_id": "emulator-5554", "avd_name": "demo", "status": "device"}])
    page.route("**/api/android/environment?*", lambda route: route.fulfill(json=environment))
    prepared, submitted = [], []

    def prepare(route):
        prepared.append(route)

    def submit(route):
        submitted.append(route.request.post_data)
        route.fulfill(status=409, json={"detail": "Verification stopped before starting a target test"})

    page.route("**/api/android/prepare", prepare)
    page.route("**/api/mobile/runs", submit)
    try:
        page.locator("#mobileModeBtn").click()
        expect(page.locator("#androidStart")).to_be_enabled()
        assert not prepared and not submitted
        expect(page.locator("#androidEnvNote")).to_contain_text("launch local Appium")
        expect(page.locator("#androidDevice")).to_have_value("emulator-5554" if previously_connected else "avd:demo")
        page.locator("#androidMode").select_option("installed")
        page.locator("#androidPackage").fill("com.example.demo")
        page.locator("#androidProvider").select_option("none")
        page.locator("#androidApiKey").fill("fixture-private-key")
        page.locator("#androidAuthorized").check()
        page.locator("#androidStart").click()
        expect(page.locator("#androidStart")).to_be_disabled()
        expect(page.locator("#androidRunNote")).to_contain_text("Starting local Appium")
        assert not submitted and len(prepared) == 1
        payload = prepared[0].request.post_data_json
        assert set(payload) == {"device_id", "avd_name", "appium_url", "authorized", "stage"}
        assert payload["stage"] == "appium"
        assert "fixture-private-key" not in prepared[0].request.post_data
        assert payload["avd_name"] == "demo"
        if failure_stage == "appium":
            prepared[0].fulfill(status=409, json={"detail": "Appium could not start"})
            expect(page.locator("#androidRunNote")).to_have_text("Appium could not start")
            assert not submitted and len(prepared) == 1
        else:
            prepared[0].fulfill(json={"appium": {"started": True, "url": "http://127.0.0.1:4723"}})
            expect(page.locator("#androidRunNote")).to_contain_text("Waiting for Android to boot")
            assert not submitted and len(prepared) == 2
            assert prepared[1].request.post_data_json["stage"] == "device"
        if failure_stage == "device":
            prepared[1].fulfill(status=409, json={"detail": "Android did not finish booting"})
            expect(page.locator("#androidRunNote")).to_have_text("Android did not finish booting")
            assert not submitted
        elif not failure_stage:
            prepared[1].fulfill(json={"device_id": "emulator-5554", "avd_name": "demo", "started": True})
            expect(page.locator("#androidRunNote")).to_contain_text("Verification stopped")
            assert len(submitted) == 1 and "emulator-5554" in submitted[0]
            assert "avd:demo" not in submitted[0]
        expect(page.locator("#androidStart")).to_be_enabled()
        expect(page.locator("#androidApiKey")).to_have_value("fixture-private-key")
        assert not errors
    finally:
        context.close()
