"""Username substring redaction must not corrupt Android package identifiers.

Live run: runs/android_live_20261112_084222 — discovery found 13 screens, then every generated
pytest errored with ``A valid app package is required before resetting its data`` because
username ``demo`` (BLOWAI_SECRET_TEST_USERNAME) turned ``com.blowai.demo`` into
``com.blowai.[REDACTED]`` inside screens.json / app_map.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.android import PACKAGE_NAME, AndroidEnvironmentError, reset_app_data
from backend.android_pipeline import _save_json
from backend.safety import REDACTED, redact, redact_json


@pytest.fixture
def demo_username_secret(monkeypatch):
    monkeypatch.setenv("BLOWAI_SECRET_TEST_USERNAME", "demo")
    monkeypatch.setenv("BLOWAI_SECRET_TEST_PASSWORD", "secret-password-never-print")
    return "demo"


def test_username_demo_does_not_corrupt_package_in_saved_screens_and_app_map(tmp_path, demo_username_secret):
    package = "com.blowai.demo"
    assert demo_username_secret in package  # the live failure mode: username is a package substring
    assert REDACTED in redact(package)  # naive redaction still corrupts the bare string

    screens = [
        {
            "id": "home",
            "package_name": package,
            "screen_name": "Home",
            "activity": ".MainActivity",
            "elements": [],
            "note": "typed secret-password-never-print into the password box",
        }
    ]
    app_map = [
        {
            "url": f"android://{package}/home",
            "slug": "home",
            "title": "Home",
            "package_name": package,
            "password_leak": "secret-password-never-print",
        }
    ]

    screens_path = tmp_path / "screens.json"
    app_map_path = tmp_path / "app_map.json"
    _save_json(screens_path, screens)
    _save_json(app_map_path, app_map)

    loaded_screens = json.loads(screens_path.read_text(encoding="utf-8"))
    loaded_map = json.loads(app_map_path.read_text(encoding="utf-8"))
    saved_screens_text = screens_path.read_text(encoding="utf-8")
    saved_map_text = app_map_path.read_text(encoding="utf-8")

    assert loaded_screens[0]["package_name"] == package
    assert loaded_map[0]["package_name"] == package
    assert loaded_map[0]["url"] == f"android://{package}/home"
    assert "com.blowai.[REDACTED]" not in saved_screens_text
    assert "com.blowai.[REDACTED]" not in saved_map_text
    assert "secret-password-never-print" not in saved_screens_text
    assert "secret-password-never-print" not in saved_map_text
    assert PACKAGE_NAME.fullmatch(loaded_screens[0]["package_name"])

    calls = []

    class Driver:
        def execute_script(self, name, args):
            calls.append((name, args))
            if name == "mobile: getPermissions":
                return []
            return None

        def activate_app(self, pkg):
            calls.append(("activate", pkg))

    reset_app_data(Driver(), loaded_screens[0]["package_name"])
    assert ("mobile: clearApp", {"appId": package}) in calls
    assert ("activate", package) in calls


def test_redact_json_restores_package_keys_used_by_reporting(demo_username_secret):
    payload = {
        "package_name": "com.blowai.demo",
        "appPackage": "com.blowai.demo",
        "hint": "user demo",
        "password_leak": "secret-password-never-print",
    }
    text = redact_json(payload)
    data = json.loads(text)
    assert data["package_name"] == data["appPackage"] == "com.blowai.demo"
    assert data["hint"] == f"user {REDACTED}"
    assert "secret-password-never-print" not in text


def test_reset_app_data_mentions_redaction_when_package_looks_corrupted():
    with pytest.raises(AndroidEnvironmentError, match="redaction") as raised:
        reset_app_data(object(), "com.blowai.[REDACTED]")
    assert "valid app package" in str(raised.value).lower()


def test_android_conftest_prefers_config_package_for_reset_and_launch():
    source = (
        Path(__file__).resolve().parents[1] / "backend" / "templates" / "android_conftest.py"
    ).read_text(encoding="utf-8")
    assert "def _app_package():" in source
    assert 'CONFIG.get("package_name")' in source
    assert "reset_app_data(driver, _app_package())" in source
    assert "driver.activate_app(_app_package())" in source
    assert 'reset_app_data(driver, SCREENS[0]["package_name"])' not in source
