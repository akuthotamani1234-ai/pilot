import zipfile

import pytest

from backend import android
from backend.android import (
    AndroidEnvironmentError,
    build_capabilities,
    extract_screen,
    parse_devices,
    validate_apk,
    validate_mobile_config,
)


def test_java_path_discovers_user_local_blowai_jdk_without_java_home(tmp_path, monkeypatch):
    executable = "java.exe" if android.os.name == "nt" else "java"
    java = tmp_path / "BlowAI" / "jdk-21" / "bin" / executable
    java.parent.mkdir(parents=True)
    java.touch()
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(android.shutil, "which", lambda _name: None)

    assert android._java_path() == str(java)


def test_parse_devices_keeps_status_and_details():
    assert parse_devices(
        "List of devices attached\nemulator-5554 device product:sdk_gphone\nphone offline\n"
    ) == [
        {"device_id": "emulator-5554", "status": "device", "details": "product:sdk_gphone"},
        {"device_id": "phone", "status": "offline", "details": ""},
    ]


def test_mobile_config_requires_local_appium_and_bounded_limits():
    config = {
        "app_mode": "installed",
        "package_name": "com.example.demo",
        "device_id": "emulator-5554",
        "max_screens": "4",
        "max_actions": "8",
    }

    assert validate_mobile_config(config)["max_screens"] == 4
    with pytest.raises(AndroidEnvironmentError, match="only on this computer"):
        validate_mobile_config({**config, "appium_url": "http://192.168.1.10:4723"})
    with pytest.raises(AndroidEnvironmentError, match="whole numbers"):
        validate_mobile_config({**config, "max_screens": "many"})
    with pytest.raises(AndroidEnvironmentError, match="0-100 screens"):
        validate_mobile_config({**config, "max_screens": 101})


def test_validate_apk_checks_manifest_and_archive(tmp_path):
    apk_path = tmp_path / "demo.apk"
    with zipfile.ZipFile(apk_path, "w") as apk:
        apk.writestr("AndroidManifest.xml", b"manifest")
        apk.writestr("classes.dex", b"dex")

    assert validate_apk(apk_path) == apk_path.resolve()

    invalid_path = tmp_path / "invalid.apk"
    with zipfile.ZipFile(invalid_path, "w") as apk:
        apk.writestr("classes.dex", b"dex")
    with pytest.raises(AndroidEnvironmentError, match="manifest missing"):
        validate_apk(invalid_path)


def test_an_apk_check_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = b"tenant-b-only-apk"
    other = tmp_path / "other"
    other.mkdir()
    (other / "app.apk").write_bytes(secret)
    (other / "keep.txt").write_bytes(secret)
    linked = tmp_path / "linked.apk"
    linked.symlink_to(other / "app.apk")
    with pytest.raises(AndroidEnvironmentError, match="link"):
        validate_apk(linked)
    parent = tmp_path / "parent"
    parent.symlink_to(other, target_is_directory=True)
    with pytest.raises(AndroidEnvironmentError, match="link"):
        validate_apk(parent / "app.apk")
    assert (other / "app.apk").read_bytes() == secret
    assert (other / "keep.txt").read_bytes() == secret
    assert not (other / "fresh").exists()

    real = tmp_path / "home.apk"
    with zipfile.ZipFile(real, "w") as apk:
        apk.writestr("AndroidManifest.xml", b"home-own")
        apk.writestr("classes.dex", b"dex")
    assert validate_apk(real) == real.resolve()
    own = real.read_bytes()
    assert b"home-own" in own and secret not in own
    assert (other / "app.apk").read_bytes() == secret


def test_validate_apk_rejects_non_apk_and_unsafe_paths(tmp_path):
    wrong_extension = tmp_path / "demo.zip"
    wrong_extension.write_bytes(b"not an apk")
    with pytest.raises(AndroidEnvironmentError, match="\\.apk"):
        validate_apk(wrong_extension)

    unsafe_path = tmp_path / "unsafe.apk"
    with zipfile.ZipFile(unsafe_path, "w") as apk:
        apk.writestr("AndroidManifest.xml", b"manifest")
        apk.writestr("classes.dex", b"dex")
        apk.writestr("../outside", b"payload")
    with pytest.raises(AndroidEnvironmentError, match="unsafe archive path"):
        validate_apk(unsafe_path)


def test_build_capabilities_supports_apk_and_installed_app(tmp_path):
    apk_path = tmp_path / "demo.apk"
    with zipfile.ZipFile(apk_path, "w") as apk:
        apk.writestr("AndroidManifest.xml", b"manifest")
        apk.writestr("classes.dex", b"dex")

    base = {"device_id": "emulator-5554", "app_activity": ".MainActivity"}
    apk_caps = build_capabilities({**base, "app_mode": "apk", "apk_path": str(apk_path)})
    installed_caps = build_capabilities({
        **base,
        "app_mode": "installed",
        "package_name": "com.example.demo",
    })

    assert apk_caps["appium:app"] == str(apk_path.resolve())
    assert installed_caps["appium:appPackage"] == "com.example.demo"
    assert installed_caps["appium:appActivity"] == ".MainActivity"
    assert installed_caps["appium:noReset"] is True
    assert apk_caps["appium:autoGrantPermissions"] is False
    for capabilities in (apk_caps, installed_caps):
        assert capabilities["appium:settings[enableNotificationListener]"] is True
        assert capabilities["appium:settings[waitForIdleTimeout]"] == 250


def test_extract_screen_orders_stable_locators_and_redacts_input_values():
    screen = extract_screen(
        '<hierarchy><node class="android.widget.EditText" resource-id="com.example:id/password" '
        'password="true" text="do-not-store" clickable="true" bounds="[0,0][100,50]"/>'
        '<node class="android.widget.Button" resource-id="com.example:id/login" '
        'content-desc="Sign in" text="Sign in" clickable="true" bounds="[0,50][100,100]"/>'
        "</hierarchy>",
        "com.example",
        "emulator-5554",
        ".LoginActivity",
    )

    password, button = screen["elements"]
    assert password["type"] == "input"
    assert password["text"] == ""
    assert password["locators"][0] == {
        "strategy": "resource_id",
        "value": "com.example:id/password",
    }
    # Prefer durable resource_id ahead of accessibility_id / text.
    assert button["locators"] == [
        {"strategy": "resource_id", "value": "com.example:id/login"},
        {"strategy": "accessibility_id", "value": "Sign in"},
        {"strategy": "text", "value": "Sign in"},
    ]
    assert screen["platform"] == "android"
    assert screen["activity"] == ".LoginActivity"


def test_extract_screen_recognizes_flutter_bottom_navigation_tabs():
    labels = (
        "Home\nTab 1 of 4",
        "Trial\nTab 2 of 4",
        "Cart\nTab 3 of 4",
        "Account\nTab 4 of 4",
    )
    def button(index, label):
        accessible_label = label.replace("\n", "&#10;")
        return (
            f'<node class="android.widget.Button" content-desc="{accessible_label}" clickable="true" '
            f'bounds="[{index * 100},0][{(index + 1) * 100},80]"/>'
        )

    buttons = "".join(button(index, label) for index, label in enumerate(labels))
    screen = extract_screen(
        f'<hierarchy><node class="android.widget.LinearLayout" bounds="[0,0][400,80]">{buttons}</node></hierarchy>',
        "com.example.shop",
        "emulator-5554",
        ".MainActivity",
    )

    tabs = [element for element in screen["elements"] if element["navigation_role"] == "tab"]
    assert [element["accessibility_id"] for element in tabs] == list(labels)
