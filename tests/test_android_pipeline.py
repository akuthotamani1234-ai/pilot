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
