import ast
import json

from backend import android_pipeline

START_XML = """<hierarchy>
<node class="android.widget.Button" resource-id="com.example:id/home" text="Home" clickable="true" bounds="[0,0][80,50]"/>
<node class="android.widget.Button" resource-id="com.example:id/delete" text="Delete account" clickable="true" bounds="[80,0][160,50]"/>
<node class="android.widget.EditText" resource-id="com.example:id/password" text="private-value" password="true" bounds="[0,50][160,100]"/>
</hierarchy>"""
HOME_XML = """<hierarchy>
<node class="android.widget.TextView" resource-id="com.example:id/title" text="Home screen" bounds="[0,0][160,50]"/>
</hierarchy>"""


class FakeElement:
    def __init__(self, driver):
        self.driver = driver

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def click(self):
        self.driver.page_source = HOME_XML


class FakeDriver:
    current_package = "com.example"
    current_activity = ".MainActivity"

    def __init__(self):
        self.page_source = START_XML
        self.quit_called = False

    def find_elements(self, _by, _value):
        return [FakeElement(self)]

    def find_element(self, _by, _value):
        return FakeElement(self)

    def back(self):
        self.page_source = START_XML

    def quit(self):
        self.quit_called = True


def _state(tmp_path):
    return {
        "config": {
            "app_mode": "installed",
            "package_name": "com.example",
            "device_id": "emulator-5554",
            "appium_url": "http://127.0.0.1:4723",
            "max_actions": 5,
            "max_screens": 5,
            "expected_destinations": {"home": "Home", "about": "About"},
        },
        "run_id": "android-test",
        "run_dir": str(tmp_path),
        "source": "Android app com.example",
        "log": [],
    }


def test_discovery_only_clicks_safe_navigation_and_restores_the_start_screen(tmp_path, monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(android_pipeline, "create_session", lambda _config: driver)

    result = android_pipeline.discovery_agent(_state(tmp_path))

    assert len(result["screens"]) == 2
    assert len(result["actions"]) == 1
    assert result["actions"][0]["label"] == "Home"
    assert result["actions"][0]["outcome"] == "observed"
    assert driver.page_source == START_XML
    assert driver.quit_called
    assert json.loads((tmp_path / "app_map.json").read_text(encoding="utf-8"))[0]["platform"] == "android"


def test_test_design_records_safe_cases_and_blocked_controls(tmp_path, monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(android_pipeline, "create_session", lambda _config: driver)
    state = android_pipeline.discovery_agent(_state(tmp_path))
    state["screens"].append({
        "fingerprint": "extra", "screen_name": "Extra", "activity": ".Extra",
        "elements": [
            {"visible": True, "enabled": True, "clickable": True, "input_capable": False, "text": "Save settings"},
            {"visible": True, "enabled": True, "clickable": True, "input_capable": False, "text": "Delete account"},
        ]
    })

    designed = android_pipeline.test_design_agent({**_state(tmp_path), **state})

    assert [case["kind"] for case in designed["test_cases"]][:2] == ["screen", "navigation"]
    assert any(case["kind"] == "ui" for case in designed["test_cases"])
    assert designed["test_cases"][-1]["kind"] == "blocked"
    assert designed["test_cases"][1]["expected_screen_name"] == "Home"
    blocked = designed["test_cases"][-1]
    assert blocked["blocked"] is True
    assert blocked["blocked_count"] == 4


def test_test_design_adds_semantic_destination_for_named_navigation(tmp_path):
    from backend.android import extract_screen
    state = _state(tmp_path)
    screen = extract_screen('<hierarchy><node class="android.widget.Button" content-desc="About" text="About" clickable="true"/></hierarchy>',
                            "com.example", "emulator-5554", ".MainActivity")
    state["screens"] = [screen]
    state["actions"] = [{"outcome": "observed", "label": "About", "locator": screen["elements"][0]["locators"][0],
                         "before_fingerprint": screen["fingerprint"], "expected_fingerprint": "settings"}]
    designed = android_pipeline.test_design_agent(state)
    case = designed["test_cases"][1]
    assert case["expected_screen_name"] == "About"
    assert case["plan"][-1] == ["assert_screen", ["About"]]
    assert case["functionality_status"] == "confirmed"


def test_discovery_respects_the_screen_limit(tmp_path, monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(android_pipeline, "create_session", lambda _config: driver)
    state = _state(tmp_path)
    state["config"]["max_screens"] = 1

    result = android_pipeline.discovery_agent(state)

    assert len(result["screens"]) == 1
    assert result["actions"] == []


def test_generated_runner_uses_trusted_template_and_json_cases(tmp_path, monkeypatch):
    from backend.android_design import normalize_case, validate_mobile_script
    state = _state(tmp_path)
    state["test_cases"] = [normalize_case({"id": "safe", "title": "Visible home", "kind": "ui", "expected": "Home is visible",
        "plan": [["open_screen", ["home"]], ["assert_visible", ["home:e0"]]]})]
    result = android_pipeline.script_generator_agent(state)
    path = tmp_path / "generated_tests" / "test_android_generated.py"
    script = path.read_text(encoding="utf-8")
    cases = json.loads((path.parent / "android_test_cases.json").read_text(encoding="utf-8"))
    ast.parse(script)
    assert validate_mobile_script(script, cases) is None
    assert "mobile.assert_visible('home:e0')" in script
    assert script.startswith("# generated by: template")
    assert [case["id"] for case in cases] == ["safe"]
    assert result["scripts"] == [str(path)]
    assert (path.parent / "conftest.py").read_text(encoding="utf-8") == (
        android_pipeline.ROOT / "backend" / "templates" / "android_conftest.py").read_text(encoding="utf-8")


def test_junit_results_keep_pass_skip_and_failure_outcomes(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text("""<testsuite>
<testcase name="test_android_case[android_launch_screen]" time="0.5"/>
<testcase name="test_android_case[android_navigation_001]" time="0.2"><failure message="screen changed">details</failure></testcase>
<testcase name="test_android_case[android_navigation_002]" time="0.1"><skipped message="not restored"/></testcase>
</testsuite>""", encoding="utf-8")
    cases = [{"id": "android_launch_screen", "title": "Launch"},
             {"id": "android_navigation_001", "title": "Open home"},
             {"id": "android_navigation_002", "title": "Open menu"}]

    results = android_pipeline._parse_junit(junit, cases)

    assert [(result["id"], result["outcome"]) for result in results] == [
        ("android_launch_screen", "passed"),
        ("android_navigation_001", "failed"),
        ("android_navigation_002", "inconclusive"),
    ]


def test_android_setup_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import pytest

    from backend.android import AndroidEnvironmentError

    secret = b"tenant-b-only-setup"
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_bytes(secret)
    (other / "app.apk").write_bytes(secret)
    calls = []
    monkeypatch.setattr(android_pipeline, "android_environment", lambda _url: calls.append("env") or {
        "ok": True, "devices": [{"device_id": "emulator-5554", "status": "device"}]})
    monkeypatch.setattr("backend.llm.llm_enabled", lambda: False)

    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    with pytest.raises(AndroidEnvironmentError, match="link"):
        android_pipeline.setup_agent(_state(linked / "run"))
    planted = tmp_path / "planted"
    planted.mkdir()
    (planted / ".private").symlink_to(other, target_is_directory=True)
    planted_state = _state(planted)
    planted_state["config"].update(app_mode="apk", package_name="", apk_path=str(planted / ".private" / "app.apk"))
    with pytest.raises(AndroidEnvironmentError, match="link"):
        android_pipeline.setup_agent(planted_state)
    assert calls == []
    assert (other / "keep.txt").read_bytes() == secret
    assert (other / "app.apk").read_bytes() == secret
    assert not (other / "run").exists()
    assert not (other / "android_environment.json").exists()

    real = tmp_path / "real"
    (real / ".private").mkdir(parents=True)
    apk = real / ".private" / "app.apk"
    apk.write_bytes(b"mine")
    state = _state(real)
    state["config"].update(app_mode="apk", package_name="", apk_path=str(apk))
    result = android_pipeline.setup_agent(state)
    assert result["environment"]["ok"] is True
    assert apk.read_bytes() == b"mine"
    saved = (real / "android_environment.json").read_text(encoding="utf-8")
    assert "emulator-5554" in saved
    assert secret.decode() not in saved
    assert (other / "keep.txt").read_bytes() == secret


def test_an_android_config_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    import pytest

    import backend.android_runner as runner
    from backend.android import AndroidEnvironmentError
    from backend.android_runner import _read_config

    secret = b"tenant-b-only-config"
    other = tmp_path / "other"
    other.mkdir()
    (other / "android_config.json").write_bytes(secret)
    (other / "app.apk").write_bytes(secret)
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(runner, "RUNS", runs)

    linked_private = runs / "run-a" / ".private"
    linked_private.parent.mkdir()
    linked_private.symlink_to(other, target_is_directory=True)
    with pytest.raises(AndroidEnvironmentError, match="link"):
        _read_config(linked_private / "android_config.json")
    assert (other / "android_config.json").read_bytes() == secret

    real = runs / "run-b" / ".private"
    real.mkdir(parents=True)
    config = {
        "app_mode": "installed", "package_name": "com.example",
        "device_id": "emulator-5554", "appium_url": "http://127.0.0.1:4723",
    }
    (real / "android_config.json").write_text(json.dumps(config), encoding="utf-8")
    loaded, run_dir = _read_config(real / "android_config.json")
    assert loaded["package_name"] == "com.example"
    assert run_dir == runs / "run-b"
    assert secret not in (real / "android_config.json").read_bytes()

    apk_dir = runs / "run-c" / ".private"
    apk_dir.mkdir(parents=True)
    (apk_dir / "app.apk").symlink_to(other / "app.apk")
    (apk_dir / "android_config.json").write_text(json.dumps({
        **config, "app_mode": "apk", "package_name": "", "apk_path": str(apk_dir / "app.apk"),
    }), encoding="utf-8")
    with pytest.raises(AndroidEnvironmentError, match="link"):
        _read_config(apk_dir / "android_config.json")
    assert (other / "app.apk").read_bytes() == secret


def test_an_android_run_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    import datetime as dt
    from pathlib import Path

    import pytest

    from backend.android_runner import prepare_android_run
    from backend.qa_benchmark import repeat_android

    secret = b"tenant-b-only-apk"
    other = tmp_path / "other"
    other.mkdir()
    (other / "app.apk").write_bytes(secret)
    (other / "android_config.json").write_bytes(secret)
    (other / "repeat.log").write_bytes(secret)

    linked_root = tmp_path / "linked-runs"
    linked_root.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="link"):
        prepare_android_run(linked_root, "android_run")
    with pytest.raises(ValueError, match="link"):
        repeat_android(tmp_path / "missing.json", 1, linked_root)
    assert (other / "app.apk").read_bytes() == secret
    assert (other / "android_config.json").read_bytes() == secret
    assert (other / "repeat.log").read_bytes() == secret

    runs = tmp_path / "runs"
    runs.mkdir()
    planted = runs / "repeat_20261119_132600_1"
    planted.symlink_to(other, target_is_directory=True)

    class _Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 19, 13, 26, 0)

    monkeypatch.setattr(dt, "datetime", _Clock)
    monkeypatch.setattr("backend.android_runner._read_config", lambda _path: ({"app_mode": "web"}, Path(".")))

    def explode(*_args, **_kwargs):
        raise AssertionError("started")

    monkeypatch.setattr("backend.android_pipeline._run_mobile_process", explode)
    with pytest.raises(ValueError, match="link"):
        repeat_android(tmp_path / "config.json", 1, runs)
    assert (other / "app.apk").read_bytes() == secret
    assert not (other / ".private").exists()

    created = prepare_android_run(runs, "android_real")
    assert (created / ".private").is_dir() and not (created / ".private").is_symlink()


def test_an_android_report_does_not_follow_a_link_into_another_run(tmp_path):
    import pytest

    from backend.android_reporting import report
    from backend.android_runner import prepare_android_run, write_android_failure

    secret = "tenant-b-only-mobile"
    other = tmp_path / "other"
    other.mkdir()
    (other / "summary.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")
    (other / "report.html").write_text(secret, encoding="utf-8")
    (other / "dynamic.json").write_text(json.dumps({"events": [{"secret": secret}]}), encoding="utf-8")
    (other / "healing_log.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")

    linked = tmp_path / "linked-run"
    linked.symlink_to(other, target_is_directory=True)
    report({"run_dir": str(linked), "run_id": "linked", "config": {}, "screens": [],
            "test_cases": [], "results": []})
    assert json.loads((other / "summary.json").read_text(encoding="utf-8"))["secret"] == secret
    assert (other / "report.html").read_text(encoding="utf-8") == secret
    assert "test_cases.json" not in {path.name for path in other.iterdir()}

    real = tmp_path / "real"
    real.mkdir()
    (real / "summary.json").symlink_to(other / "summary.json")
    (real / "report.html").symlink_to(other / "report.html")
    (real / "dynamic.json").symlink_to(other / "dynamic.json")
    (real / "healing_log.json").symlink_to(other / "healing_log.json")
    report({"run_dir": str(real), "run_id": "real", "config": {}, "screens": [],
            "test_cases": [], "results": []})
    assert (real / "summary.json").is_symlink()
    assert (real / "report.html").is_symlink()
    assert (real / "healing_log.json").is_symlink()
    assert json.loads((other / "summary.json").read_text(encoding="utf-8"))["secret"] == secret
    assert (other / "report.html").read_text(encoding="utf-8") == secret
    assert (other / "healing_log.json").read_text(encoding="utf-8") == json.dumps({"secret": secret})
    for path in real.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        assert secret not in path.read_text(encoding="utf-8", errors="replace")

    runs = tmp_path / "runs"
    planted = runs / "android_report"
    planted.mkdir(parents=True)
    (planted / "report.html").symlink_to(other / "report.html")
    with pytest.raises(ValueError, match="link"):
        prepare_android_run(runs, "android_report")
    assert (other / "report.html").read_text(encoding="utf-8") == secret

    assert write_android_failure(real, "real", "Android app", "boom") is False
    assert (other / "report.html").read_text(encoding="utf-8") == secret
    plain = tmp_path / "plain"
    plain.mkdir()
    assert write_android_failure(plain, "plain", "Android app", "boom") is True
    assert "Insufficient Evidence" in (plain / "report.html").read_text(encoding="utf-8")
    assert json.loads((plain / "summary.json").read_text(encoding="utf-8"))["verdict"] == "Insufficient Evidence"
