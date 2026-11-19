"""An ApiDemos interaction stays in this install. A link does not start a device."""
import sys
import types

from backend.apidemos_interaction_drill import run_apidemos_interaction_drill
from backend.blueprint_progress import progress


def _install_appium_standin() -> list[str]:
    if "appium.webdriver.common.appiumby" in sys.modules:
        return []
    appiumby = types.ModuleType("appium.webdriver.common.appiumby")

    class AppiumBy:
        ANDROID_UIAUTOMATOR = "uiautomator"

    appiumby.AppiumBy = AppiumBy
    added = []
    for name in ("appium", "appium.webdriver", "appium.webdriver.common"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
            added.append(name)
    sys.modules["appium.webdriver.common.appiumby"] = appiumby
    added.append("appium.webdriver.common.appiumby")
    return added


def test_an_apidemos_interaction_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.apidemos_interaction_drill as mod

    calls = {"n": 0}

    def _env(_url):
        calls["n"] += 1
        return {"adb": "adb"}

    def _online(_env_info):
        calls["n"] += 1
        return [{"device_id": "emulator-5554", "api_level": 30}]

    def _ready(_url):
        calls["n"] += 1
        return True

    def _install(_adb, _serial):
        calls["n"] += 1
        return {"installed": True}

    def _activity(_serial, _package):
        calls["n"] += 1
        return ".ApiDemos"

    class _Element:
        def click(self):
            return None

    class _Driver:
        current_package = mod.APIDEMOS_PACKAGE
        page_source = "<hierarchy/>"

        def find_element(self, _by, _value):
            return _Element()

        def find_elements(self, _by, _value):
            return [_Element()]

    def _session(_cfg):
        calls["n"] += 1
        return _Driver()

    def _close(_driver):
        calls["n"] += 1
        return None

    monkeypatch.setattr(mod, "android_environment", _env)
    monkeypatch.setattr(mod, "_online_emulators", _online)
    monkeypatch.setattr(mod, "_appium_ready", _ready)
    monkeypatch.setattr(mod, "_ensure_apidemos", _install)
    monkeypatch.setattr(mod, "launchable_activity", _activity)
    monkeypatch.setattr(mod, "create_session", _session)
    monkeypatch.setattr(mod, "close_session", _close)
    added = _install_appium_standin()

    secret = "tenant-b-apidemos"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "apidemos_interaction_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_apidemos_interaction_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_apidemos_interaction_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_apidemos_interaction_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["ok"] is True
    assert calls["n"] == 7
    assert "ApiDemos deep interaction" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original
    for name in added:
        sys.modules.pop(name, None)


def test_apidemos_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-apidemos-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-apidemos-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert snap["complete"] is False
