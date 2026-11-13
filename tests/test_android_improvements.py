"""Regression checks for the audited bugs and the mobile safety/AI contracts."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from selenium.common.exceptions import NoSuchElementException

from backend import android, android_design, android_pipeline, server
from backend.agents.reporter import decide_verdict
from backend.agents.test_design import validate_case
from backend.android_reporting import classify_failure
from backend.android_runtime import MobileRuntime
from tests.test_android_pipeline import FakeDriver, _state


@pytest.mark.parametrize(
    "change",
    [
        {"package_name": "bad"},
        {"app_mode": "bad"},
        {"max_screens": "101"},
        {"max_depth": "11"},
        {"expected_destinations": "not a mapping"},
        {"appium_url": "http://192.168.1.2:4723"},
    ],
)
def test_invalid_mobile_requests_are_client_errors(change):
    client = TestClient(server.app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False)
    payload = {"authorized": "true", "app_mode": "installed", "package_name": "com.example.demo", "device_id": "review"}
    response = client.post("/api/mobile/runs", headers={"X-Agentic-QA": "1"}, data={**payload, **change})
    assert response.status_code == 400, response.text


def test_foreground_package_is_checked_before_external_hierarchy_is_read():
    class ExternalDriver:
        current_package = "com.android.settings"

        @property
        def page_source(self):
            pytest.fail("External hierarchy must never be read")

    with pytest.raises(android.AndroidEnvironmentError, match="left the selected"):
        android.inspect_driver(ExternalDriver(), {"package_name": "com.example", "device_id": "test"})


@pytest.mark.parametrize(
    "outcomes, expected",
    [
        (["passed", "failed"], "Not Ready"),
        (["failed"], "Not Ready"),
        (["error"], "Insufficient Evidence"),
        (["blocked"], "Insufficient Evidence"),
        (["passed", "inconclusive"], "Insufficient Evidence"),
        (["passed"], "Ready"),
    ],
)
def test_shared_verdict_uses_actual_mobile_evidence(outcomes, expected):
    state = {
        "target_type": "mobile",
        "screens": [{"id": "s1"}],
        "results": [
            {
                "id": str(i),
                "outcome": outcome,
                "exception_type": "AssertionError" if outcome == "failed" else "",
                "error": "",
            }
            for i, outcome in enumerate(outcomes)
        ],
    }
    assert decide_verdict(state)[0] == expected


def test_assertion_with_appium_source_in_traceback_is_not_infrastructure():
    result = {"outcome": "failed", "error": "AssertionError: wrong destination\n driver = create_session(AppiumBy.ID)"}
    assert classify_failure(result) == "assertion_failure"
    assert classify_failure({**result, "exception_type": "NoSuchElementException"}) == "locator"


def test_disconnect_during_cleanup_preserves_discovery(tmp_path, monkeypatch):
    driver = FakeDriver()

    def broken_quit():
        raise RuntimeError("device disconnected")

    monkeypatch.setattr(driver, "quit", broken_quit)
    monkeypatch.setattr(android_pipeline, "create_session", lambda _: driver)
    state = _state(tmp_path)
    # Soft caps: 0 = until exhausted. Keep this cleanup test to a single launch screen.
    state["config"]["max_screens"] = 1
    state["config"]["max_actions"] = 1
    (tmp_path / "STOP").write_text("stop", encoding="utf-8")
    result = android_pipeline.discovery_agent(state)
    assert len(result["screens"]) >= 1
    assert json.loads((tmp_path / "screens.json").read_text(encoding="utf-8"))
    assert any("cleanup" in issue["error"].lower() for issue in result["discovery_issues"])


def test_device_lock_prevents_concurrent_sessions_and_releases():
    with android.DeviceLock("blowai-regression-lock-test"):
        with pytest.raises(android.AndroidEnvironmentError, match="already controlled"):
            with android.DeviceLock("blowai-regression-lock-test"):
                pytest.fail("A second lock was acquired")
    with android.DeviceLock("blowai-regression-lock-test"):
        pass


def _designed(tmp_path, monkeypatch):
    monkeypatch.setattr(android_pipeline, "create_session", lambda _: FakeDriver())
    state = _state(tmp_path)
    state.update(android_pipeline.discovery_agent(state))
    state.update(android_pipeline.test_design_agent(state))
    return state


def test_mobile_cases_use_shared_schema_and_case_status_api(tmp_path, monkeypatch):
    state = _designed(tmp_path, monkeypatch)
    assert all(validate_case(case) == [] for case in state["test_cases"])
    state.update(android_pipeline.script_generator_agent(state))
    result = {
        "id": state["test_cases"][0]["id"],
        "outcome": "passed",
        "file": "test_android_generated.py",
        "test": "test_android_launch_screen",
    }
    (tmp_path / "results.json").write_text(json.dumps([result]), encoding="utf-8")
    status = server._case_progress(tmp_path, False)
    assert status["cases"][0]["status"] == "Passed"


def test_unknown_destinations_are_not_invented(tmp_path, monkeypatch):
    monkeypatch.setattr(android_pipeline, "create_session", lambda _: FakeDriver())
    state = _state(tmp_path)
    state["config"]["expected_destinations"] = {}
    state.update(android_pipeline.discovery_agent(state))
    result = android_pipeline.test_design_agent(state)
    case = next(c for c in result["test_cases"] if c["id"].startswith("android_navigation"))
    assert case["functionality_status"] == "inferred"
    assert case["expected_screen_name"] is None
    assert not any(step[0] == "tap" for step in case["plan"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda code: "import os\n" + code,
        lambda code: code.replace("(mobile):", "(mobile=print('unsafe')):"),
        lambda code: code.replace("mobile.assert_visible", "mobile.driver.execute_script"),
        lambda code: code.replace("mobile.assert_visible('home:e0')", "assert True"),
        lambda code: code.replace("'home:e0'", "'invented:e0'"),
        lambda code: "@print('unsafe')\n" + code,
    ],
)
def test_mobile_ast_validation_rejects_escapes_and_weakened_assertions(mutation):
    cases = [{"id": "safe", "plan": [["open_screen", ["home"]], ["assert_visible", ["home:e0"]]]}]
    code = "def test_safe(mobile):\n    mobile.open_screen('home')\n    mobile.assert_visible('home:e0')\n"
    assert android_design.validate_mobile_script(code, cases) is None
    assert android_design.validate_mobile_script(mutation(code), cases)


def test_ai_script_is_validated_and_records_real_generation_source(tmp_path, monkeypatch):
    state = _designed(tmp_path, monkeypatch)
    monkeypatch.setattr(android_design.llm, "llm_enabled", lambda: True)

    def ai_code(*_args, **_kwargs):
        return "\n\n".join(
            "def test_"
            + c["id"]
            + "(mobile):\n"
            + "\n".join(
                "    mobile." + method + "(" + ", ".join(repr(a) for a in args) + ")" for method, args in c["plan"]
            )
            for c in state["test_cases"]
            if not c.get("blocked")
        )

    monkeypatch.setattr(android_design.llm, "ask_llm", ai_code)
    generated = android_pipeline.script_generator_agent(state)
    assert generated["script_sources"] == {"test_android_generated.py": "llm"}
    assert not generated["script_errors"]


def test_unsafe_ai_script_falls_back_to_validated_template(tmp_path, monkeypatch):
    state = _designed(tmp_path, monkeypatch)
    monkeypatch.setattr(android_design.llm, "llm_enabled", lambda: True)
    monkeypatch.setattr(android_design.llm, "ask_llm", lambda *_a, **_k: "import os\nos.system('bad')")
    generated = android_pipeline.script_generator_agent(state)
    assert generated["script_sources"] == {"test_android_generated.py": "template"}
    assert generated["script_errors"]
    cases = [c for c in state["test_cases"] if not c.get("blocked")]
    assert (
        android_design.validate_mobile_script(Path(generated["scripts"][0]).read_text(encoding="utf-8"), cases) is None
    )


def test_locator_recovery_requires_unique_same_element_and_keeps_assertions(tmp_path, monkeypatch):
    original = android.extract_screen(
        '<hierarchy><node class="android.widget.TextView" text="Home" resource-id="title"/>'
        '<node class="android.widget.Button" text="About" resource-id="old" content-desc="About" clickable="true"/></hierarchy>',
        "com.example",
        "test",
        ".Main",
    )
    android_design.normalize_screens([original])
    original["elements"][1]["locators"].reverse()
    original["elements"][1]["locators"] = [{"strategy": "resource_id", "value": "old"}]
    live = android.extract_screen(
        '<hierarchy><node class="android.widget.TextView" text="Home" resource-id="title"/>'
        '<node class="android.widget.Button" text="About" resource-id="new" content-desc="About" clickable="true"/></hierarchy>',
        "com.example",
        "test",
        ".Main",
    )

    class Element:
        def is_displayed(self):
            return True

    def find(_driver, locator):
        if locator["value"] == "old":
            raise NoSuchElementException("old locator is gone")
        return Element()

    monkeypatch.setattr("backend.android_runtime.find_unique", find)
    monkeypatch.setattr("backend.android_runtime.inspect_driver", lambda *_: live)
    runtime = MobileRuntime(object(), {"device_id": "test"}, [original], {}, tmp_path)
    runtime.assert_visible(original["elements"][1]["id"])
    assert runtime.checks == 1
    assert len(runtime.healing) == 1
    assert runtime.healing[0]["original_locator"]["value"] == "old"
    assert runtime.healing[0]["replacement_locator"]["value"] == "About"
    assert runtime.healing[0]["lookup_outcome"] == "recovered"


def test_ai_design_rejects_undiscovered_references(tmp_path, monkeypatch):
    state = _designed(tmp_path, monkeypatch)
    screen = state["screens"][0]
    element = screen["elements"][0]
    monkeypatch.setattr(android_design.llm, "llm_enabled", lambda: True)
    proposals = [
        android_design.MobileProposal(title="invented", screen_id=screen["id"], element_ids=["missing"]),
        android_design.MobileProposal(title="Observed control", screen_id=screen["id"], element_ids=[element["id"]]),
    ]
    monkeypatch.setattr(android_design.llm, "ask_structured", lambda *_a, **_k: proposals)
    result = android_pipeline.test_design_agent(state)
    ai = [c for c in result["test_cases"] if c["generation_source"] == "llm"]
    assert len(ai) == 1 and ai[0]["title"] == "UI: Observed control"
    assert any("Rejected" in note for note in result["log"])


def test_explicit_value_requirements_are_not_replaced_by_observed_wrong_values(tmp_path):
    screen = android.extract_screen(
        '<hierarchy><node class="android.widget.TextView" content-desc="Cart total" text="Total: $7.00"/></hierarchy>',
        "com.example",
        "test",
        ".Cart",
    )
    state = _state(tmp_path)
    state.update(screens=[screen], actions=[])
    state["config"]["expected_values"] = {"cart total": "Total: $0.00"}
    result = android_pipeline.test_design_agent(state)
    case = next(c for c in result["test_cases"] if c["id"].startswith("android_ui_"))
    assert case["plan"][-1] == ["assert_text", [screen["elements"][0]["id"], "Total: $0.00"]]
    assert case["requirement"] == "User-supplied expected displayed value"


def test_undiscovered_plan_reference_is_rejected_before_generation(tmp_path, monkeypatch):
    state = _designed(tmp_path, monkeypatch)
    state["test_cases"][0]["plan"][1][1] = ["invented"]
    with pytest.raises(ValueError, match="undiscovered"):
        android_pipeline.script_generator_agent(state)


def test_screenshots_do_not_capture_external_apps(tmp_path):
    class External:
        current_package = "com.android.settings"

        @property
        def page_source(self):
            pytest.fail("External UI must not be read for a screenshot")

    assert android.capture_screenshot(External(), tmp_path, "external", "com.example") is None


def test_screenshots_do_not_persist_entered_input_values(tmp_path):
    class Sensitive:
        current_package = "com.example"
        page_source = '<hierarchy><node class="android.widget.EditText" text="private-entered-value"/></hierarchy>'

        def save_screenshot(self, _path):
            pytest.fail("Entered input data must not be captured")

    assert android.capture_screenshot(Sensitive(), tmp_path, "private", "com.example") is None


def test_system_ui_is_excluded_from_native_screen_names():
    screen = android.extract_screen(
        '<hierarchy><node package="com.android.systemui" class="android.widget.TextView" text="12:34"/>'
        '<node package="com.example" class="android.widget.TextView" text="Home"/></hierarchy>',
        "com.example",
        "test",
    )
    assert screen["screen_name"] == "Home"
    assert len(screen["elements"]) == 1


def test_launch_case_prefers_stable_heading_over_ambiguous_layout(tmp_path):
    screen = android.extract_screen(
        '<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][100,100]"/>'
        '<node class="android.widget.FrameLayout" bounds="[0,0][100,100]"/>'
        '<node class="android.widget.TextView" content-desc="Heading" text="Home"/></hierarchy>',
        "com.example",
        "test",
    )
    state = _state(tmp_path)
    state.update(screens=[screen], actions=[])
    designed = android_pipeline.test_design_agent(state)
    launch = designed["test_cases"][0]
    heading = next(e for e in screen["elements"] if e.get("accessibility_id") == "Heading")
    assert launch["plan"][-1] == ["assert_visible", [heading["id"]]]


def test_ollama_respects_configured_request_timeout(monkeypatch):
    from backend import llm

    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "ok"}, "prompt_eval_count": 1, "eval_count": 1}

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(llm.settings, "llm_provider", "ollama")
    monkeypatch.setattr(llm.settings, "llm_timeout", 17)
    from backend import privacy
    monkeypatch.setattr(privacy, "local_ai_request", post)
    assert llm._ask_once("test", "", 0.2)[0] == "ok"
    assert captured["timeout"] == 17


def test_ollama_structured_calls_send_the_actual_json_schema(monkeypatch):
    from backend import llm

    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": "ok"}}

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(llm.settings, "llm_provider", "ollama")
    from backend import privacy
    monkeypatch.setattr(privacy, "local_ai_request", post)
    schema = {"type": "array", "maxItems": 3, "items": {"type": "string", "enum": ["E1"]}}
    llm._ask_once("test", "", 0, response_schema=schema)
    assert captured["json"]["format"] == schema


def test_input_expectations_do_not_leak_credentials_into_scripts(tmp_path):
    screen = android.extract_screen(
        '<hierarchy><node class="android.widget.EditText" content-desc="Password" text=""/></hierarchy>',
        "com.example",
        "test",
    )
    state = _state(tmp_path)
    state.update(screens=[screen], actions=[])
    state["config"]["expected_values"] = {"password": "never-persist-this-input"}
    designed = android_pipeline.test_design_agent(state)
    assert "never-persist-this-input" not in json.dumps(designed["test_cases"])


def test_observed_label_change_needs_review_instead_of_inventing_a_business_defect():
    state = {
        "target_type": "mobile",
        "screens": [{"id": "s"}],
        "test_cases": [{"id": "label", "requirement": "Observed UI regression evidence"}],
        "results": [
            {"id": "launch", "outcome": "passed"},
            {"id": "label", "outcome": "failed", "exception_type": "AssertionError"},
        ],
    }
    verdict, reasons, gates = decide_verdict(state)
    assert verdict == "Ready with Risks"
    assert any(g["id"] == "observed_changes" and g["status"] == "risk" for g in gates)


def test_authentication_wall_is_insufficient_evidence_even_when_visible_controls_pass():
    state = {
        "target_type": "mobile",
        "screens": [{"id": "login", "elements": [{"input_capable": True, "accessibility_id": "Password"}]}],
        "results": [{"id": "visible_login_fields", "outcome": "passed"}],
    }
    assert decide_verdict(state)[0] == "Insufficient Evidence"


@pytest.mark.parametrize(
    "resource,label",
    [
        ("com.example:id/checkout", "Settings"),
        ("com.example:id/place_order", "Home"),
        ("com.example:id/payment", "Continue"),
        ("com.example:id/buy_now", "Settings"),
    ],
)
def test_payment_identifiers_cannot_hide_behind_safe_navigation_labels(resource, label):
    screen = android.extract_screen(
        f'<hierarchy><node class="android.widget.Button" resource-id="{resource}" text="{label}" clickable="true"/></hierarchy>',
        "com.example",
        "test",
    )
    assert android.safe_navigation_elements(screen) == []


def test_mobile_timeout_kills_child_processes(tmp_path):
    import os
    import sys
    import time

    sentinel = tmp_path / "orphan-ran.txt"
    child_code = (
        "import time; from pathlib import Path; time.sleep(2); Path(" + repr(str(sentinel)) + ").write_text('orphan')"
    )
    parent_code = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
        + repr(child_code)
        + "]); print('started',flush=True); time.sleep(60)"
    )
    started = time.monotonic()
    completed, timed_out = android_pipeline._run_mobile_process(
        [sys.executable, "-u", "-c", parent_code], os.environ.copy(), 0.5
    )
    assert timed_out
    assert time.monotonic() - started < 15
    assert completed.returncode != 0
    time.sleep(2.2)
    assert not sentinel.exists(), "The timed-out test worker left a child process running"


def test_password_textview_never_persists_password_in_locator_or_label():
    screen = android.extract_screen(
        '<hierarchy><node class="android.widget.TextView" password="true" '
        'content-desc="secret-value" text="secret-value" resource-id="com.example:id/secret"/></hierarchy>',
        "com.example",
        "test",
    )
    assert "secret-value" not in json.dumps(screen)


def test_forced_worker_cleanup_closes_only_recorded_local_session(tmp_path, monkeypatch):
    private = tmp_path / ".private"
    private.mkdir()
    evidence = private / "active_appium_session.json"
    evidence.write_text(json.dumps({"session_id": "owned-session"}), encoding="utf-8")
    requests = []

    class Client:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def delete(self, url, **kwargs):
            assert not self.trust_env
            requests.append(url)
            return type("Response", (), {"status_code": 200})()

    monkeypatch.setattr(android_pipeline.requests, "Session", Client)
    assert android_pipeline._cleanup_worker_session(tmp_path, {"appium_url": "http://127.0.0.1:4723"}) == ""
    assert requests == ["http://127.0.0.1:4723/session/owned-session"]
    assert not evidence.exists()
    evidence.write_text(json.dumps({"session_id": "../another-session"}), encoding="utf-8")
    assert android_pipeline._cleanup_worker_session(tmp_path, {"appium_url": "http://127.0.0.1:4723"})
    assert len(requests) == 1
    assert evidence.exists()
