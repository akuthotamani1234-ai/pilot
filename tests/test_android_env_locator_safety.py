"""Phase 6 offline checks: environment readiness messages and native/WebView locator boundaries."""

import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from backend import android, android_emulator as emu
from backend.android import (
    AndroidEnvironmentError,
    find_unique,
    require_device,
    validate_apk,
    validate_mobile_config,
)
from backend.qa_contracts import Locator
from backend.qa_runtime import AndroidContractAdapter


def _ok_environment(**overrides):
    base = {
        "ok": True,
        "appium": {"available": True, "url": "http://127.0.0.1:4723"},
        "appium_cli": True,
        "java": "/jdk/bin/java",
        "uiautomator2": True,
        "android_sdk": "/sdk",
        "adb": "/sdk/platform-tools/adb",
        "devices": [{"device_id": "emulator-5554", "status": "device", "details": ""}],
        "errors": [],
        "driver_output": "UiAutomator2 verified",
    }
    base.update(overrides)
    return base


def test_android_environment_reports_unauthorized_devices_not_as_success(monkeypatch):
    monkeypatch.setattr(android, "_local_appium_url", lambda url: url.rstrip("/"))
    monkeypatch.setattr(android, "_sdk_path", lambda: "/sdk")
    monkeypatch.setattr(android, "_adb_path", lambda: "/sdk/platform-tools/adb")
    monkeypatch.setattr(android, "_appium_path", lambda: "/usr/bin/appium")
    monkeypatch.setattr(android, "_java_path", lambda: "/jdk/bin/java")
    monkeypatch.setattr(android, "_uiautomator_installation", lambda: "UiAutomator2 3 verified")
    monkeypatch.setattr(
        android.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", 'openjdk version "17.0.0"'),
    )
    monkeypatch.setattr(
        android,
        "_run_cli",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, "List of devices attached\nphone unauthorized usb:1\n", ""
        ),
    )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"value": {"ready": True, "message": "ok"}}

    class Session:
        trust_env = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(android.requests, "Session", Session)

    status = android.android_environment()
    assert status["ok"] is False
    assert status["devices"][0]["status"] == "unauthorized"
    assert any("No authorized Android device is ready" in error for error in status["errors"])
    assert not any(error.startswith("No Android device is connected.") for error in status["errors"])


def test_startup_choices_still_allow_emulator_when_only_device_unreadiness(monkeypatch):
    monkeypatch.setattr(emu, "list_emulators", lambda sdk: [{"name": "demo", "device_id": "avd:demo"}])
    monkeypatch.setattr(emu, "connected_avd_name", lambda *a: None)
    env = _ok_environment(
        ok=False,
        devices=[{"device_id": "emulator-5554", "status": "offline", "details": ""}],
        errors=["No authorized Android device is ready for testing. Seen: emulator-5554 (offline)."],
    )
    choices = emu.startup_choices(env)
    assert choices["can_start_emulator"] is True
    env["errors"].append("Java not found. Install JDK 17 or newer.")
    assert emu.startup_choices(env)["can_start_emulator"] is False


def test_require_device_messages_distinguish_unauthorized_and_offline():
    devices = [
        {"device_id": "phone", "status": "unauthorized", "details": ""},
        {"device_id": "emulator-5554", "status": "offline", "details": ""},
    ]
    with pytest.raises(AndroidEnvironmentError, match="unauthorized"):
        require_device("phone", devices)
    with pytest.raises(AndroidEnvironmentError, match="offline"):
        require_device("emulator-5554", devices)
    with pytest.raises(AndroidEnvironmentError, match="not connected"):
        require_device("missing", devices)


def test_ensure_device_ready_names_missing_sdk_and_adb(monkeypatch):
    monkeypatch.setattr(emu, "_sdk_path", lambda: None)
    monkeypatch.setattr(emu, "_adb_path", lambda: None)
    with pytest.raises(AndroidEnvironmentError, match="Android SDK .* ADB"):
        emu.ensure_device_ready("avd:demo")


def test_validate_apk_rejects_empty_and_dex_less_archives(tmp_path):
    empty = tmp_path / "empty.apk"
    empty.write_bytes(b"")
    with pytest.raises(AndroidEnvironmentError, match="empty"):
        validate_apk(empty)

    no_dex = tmp_path / "no-dex.apk"
    with zipfile.ZipFile(no_dex, "w") as apk:
        apk.writestr("AndroidManifest.xml", b"manifest")
    with pytest.raises(AndroidEnvironmentError, match="DEX bytecode missing"):
        validate_apk(no_dex)

    multi = tmp_path / "multi.apk"
    with zipfile.ZipFile(multi, "w") as apk:
        apk.writestr("AndroidManifest.xml", b"manifest")
        apk.writestr("classes2.dex", b"dex")
    assert validate_apk(multi) == multi.resolve()


def test_apk_mode_config_defers_apk_path_to_upload_layer():
    # validate_mobile_config runs before the server saves the UploadFile; apk_path is set after validate_apk.
    cfg = validate_mobile_config({"app_mode": "apk", "device_id": "emulator-5554"})
    assert cfg["app_mode"] == "apk"
    assert not (cfg.get("apk_path") or "").strip()
    with pytest.raises(AndroidEnvironmentError, match="valid Android package name"):
        validate_mobile_config({"app_mode": "installed", "device_id": "emulator-5554"})


def test_find_unique_rejects_css_in_native_context_and_keeps_it_for_webview():
    calls = []

    class Element:
        def is_displayed(self):
            return True

    visible = Element()

    class NativeDriver:
        current_context = "NATIVE_APP"

        def find_elements(self, *args):
            calls.append(("native", args))
            return [visible]

    class WebDriver:
        current_context = "WEBVIEW_com.example"

        def find_elements(self, *args):
            calls.append(("web", args))
            return [visible]

    with pytest.raises(ValueError, match="CSS selectors belong to WebView"):
        find_unique(NativeDriver(), {"strategy": "css", "value": "#login"})
    assert find_unique(WebDriver(), {"strategy": "css", "value": "#login"}) is visible
    assert calls and calls[0][0] == "web"
    with pytest.raises(ValueError, match="Unsupported locator strategy"):
        find_unique(NativeDriver(), {"strategy": "id", "value": "x"})


def test_contract_adapter_preserves_css_only_in_webview(monkeypatch):
    class Driver:
        current_context = "NATIVE_APP"
        contexts = ["NATIVE_APP", "WEBVIEW_com.example"]

        def find_elements(self, using, value):
            class Element:
                def is_displayed(self):
                    return True

            return [Element()]

        class _Switch:
            def context(self, name):
                Driver.current_context = name

        @property
        def switch_to(self):
            return Driver._Switch()

        @property
        def current_url(self):
            return "https://example.test/app"

        @property
        def current_package(self):
            return "com.example"

    monkeypatch.setattr("backend.qa_runtime.time.sleep", lambda *_: None)
    adapter = AndroidContractAdapter(
        Driver(),
        {"package_name": "com.example", "app_mode": "apk", "device_id": "emulator-5554"},
        None,
    )
    monkeypatch.setattr(adapter, "guard", lambda: None)
    css = Locator(strategy="css", value="#ok")
    with pytest.raises(ValueError, match="not native UI"):
        adapter.find(css)
    adapter.active = "webview"
    with pytest.raises(ValueError, match="need CSS selectors"):
        adapter.find(Locator(strategy="accessibility_id", value="Ok"))
    assert adapter.find(css) is not None


def test_setup_agent_surfaces_joined_environment_errors(tmp_path, monkeypatch):
    from backend import android_pipeline

    state = {
        "run_dir": str(tmp_path),
        "config": {
            "app_mode": "installed",
            "package_name": "com.example.demo",
            "device_id": "emulator-5554",
            "max_screens": 4,
            "max_actions": 8,
        },
        "log": [],
    }
    monkeypatch.setattr(
        android_pipeline,
        "android_environment",
        lambda *_: {
            "ok": False,
            "devices": [],
            "errors": [
                "ADB not found. Install Android SDK Platform-Tools.",
                "Appium server is not running at http://127.0.0.1:4723.",
            ],
            "adb": None,
            "appium": {"available": False},
        },
    )
    with pytest.raises(AndroidEnvironmentError, match="ADB not found.*Appium server is not running"):
        android_pipeline.setup_agent(state)
    saved = json.loads(Path(tmp_path, "android_environment.json").read_text(encoding="utf-8"))
    assert saved["ok"] is False
