"""Username substring redaction must not corrupt Android package identifiers.

Live run: runs/android_live_20261112_084222 — discovery found 13 screens, then every generated
pytest errored with ``A valid app package is required before resetting its data`` because
username ``demo`` (BLOWAI_SECRET_TEST_USERNAME) turned ``com.blowai.demo`` into
``com.blowai.[REDACTED]`` inside screens.json / app_map.json.

Live run: runs/android_live_20261112_085209 — the same username still corrupted QA contracts
(``android_package``) and coverage URLs that only embed the package as ``android://...``.

Live run: runs/android_live_20261112_090634 — private ``auto_contract.json`` redacted UI labels that
embed the username (``Welcome demo user`` → ``Welcome [REDACTED] user``), so replay assertions failed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.android import PACKAGE_NAME, AndroidEnvironmentError, reset_app_data
from backend.android_pipeline import _save_json
from backend.qa_contracts import parse_contract
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


def test_save_json_keeps_contract_android_package_valid(tmp_path, demo_username_secret):
    """Public auto_flows.json uses redact_json; android_package must still stay valid (live 085209)."""
    package = "com.blowai.demo"
    assert demo_username_secret in package
    contract = {
        "version": 1,
        "test_environment": True,
        "test_mode": True,
        "android_package": package,
        "flows": [
            {
                "id": "auto_tap_1",
                "title": "login as demo with secret-password-never-print",
                "approved": True,
                "steps": [{"action": "assert_screen", "value": "Home"}],
            }
        ],
    }
    path = tmp_path / "auto_flows.json"
    _save_json(path, contract)

    saved_text = path.read_text(encoding="utf-8")
    loaded = json.loads(saved_text)
    assert loaded["android_package"] == package
    assert "com.blowai.[REDACTED]" not in saved_text
    assert "secret-password-never-print" not in saved_text
    assert f"login as {REDACTED}" in saved_text
    assert PACKAGE_NAME.fullmatch(loaded["android_package"])
    parsed = parse_contract(loaded)
    assert parsed.android_package == package


def test_private_auto_contract_keeps_username_ui_assertions(tmp_path, demo_username_secret):
    """Private auto_contract.json must keep UI text that embeds the test username (live 090634).

    Observed labels like 'Welcome demo user' become assert_text locators; redacting the private
    contract made execution look for 'Welcome [REDACTED] user' and fail.
    """
    package = "com.blowai.demo"
    welcome = f"Welcome {demo_username_secret} user"
    contract = {
        "version": 1,
        "test_environment": True,
        "test_mode": True,
        "android_package": package,
        "flows": [
            {
                "id": "auto_action_008",
                "title": f"Dashboard shows {welcome}",
                "approved": True,
                "steps": [
                    {
                        "action": "assert_text",
                        "locator": {"strategy": "accessibility_id", "value": welcome},
                        "value": welcome,
                    }
                ],
            }
        ],
    }
    private = tmp_path / ".private" / "auto_contract.json"
    public = tmp_path / "auto_flows.json"
    private.parent.mkdir(parents=True, exist_ok=True)
    # Match android_pipeline discovery finish: private raw, public redacted.
    private.write_text(json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8")
    _save_json(public, contract)

    private_loaded = json.loads(private.read_text(encoding="utf-8"))
    assert private_loaded["flows"][0]["steps"][0]["value"] == welcome
    assert private_loaded["flows"][0]["steps"][0]["locator"]["value"] == welcome
    assert REDACTED not in private.read_text(encoding="utf-8")
    assert parse_contract(private_loaded).android_package == package

    public_text = public.read_text(encoding="utf-8")
    assert json.loads(public_text)["android_package"] == package
    assert f"Welcome {REDACTED} user" in public_text
    assert "secret-password-never-print" not in public_text

    pipeline = (
        Path(__file__).resolve().parents[1] / "backend" / "android_pipeline.py"
    ).read_text(encoding="utf-8")
    assert '".private" / "auto_contract.json"' in pipeline
    assert "json.dumps(contract, indent=2, ensure_ascii=False)" in pipeline


def test_redact_json_keeps_package_inside_android_urls_without_package_key(demo_username_secret):
    """coverage.json often has the package only inside android:// URLs (live 085209)."""
    package = "com.blowai.demo"
    payload = {
        "visited": [{"url": f"android://{package}/screen_x", "title": "Screen X"}],
        "hint": "user demo",
        "password_leak": "secret-password-never-print",
    }
    text = redact_json(payload)
    data = json.loads(text)
    assert data["visited"][0]["url"] == f"android://{package}/screen_x"
    assert "com.blowai.[REDACTED]" not in text
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

    runtime_source = (
        Path(__file__).resolve().parents[1] / "backend" / "android_runtime.py"
    ).read_text(encoding="utf-8")
    assert 'raw["android_package"] = package' in runtime_source
    assert "[REDACTED]" in runtime_source
