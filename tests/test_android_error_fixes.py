"""Regressions for the three-method demo's launch, budget and provider failures."""
import json

import pytest
import requests
from playwright.sync_api import expect

from backend import android, android_design, android_pipeline, android_reporting, llm
from backend.android_web import inspect_web
from tests.test_android_pipeline import START_XML, FakeDriver, _state
from tests.test_results_layout import browser as shared_browser, running_studio, studio


@pytest.fixture(scope="module")
def browser():
    yield from shared_browser.__wrapped__()


def test_recovery_does_not_exhaust_the_exploration_action_budget(tmp_path, monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(android_pipeline, "create_session", lambda _: driver)
    monkeypatch.setattr(android_pipeline.time, "sleep", lambda _: None)
    state = _state(tmp_path)
    state["config"]["max_actions"] = 1
    result = android_pipeline.discovery_agent(state)
    evidence = json.loads((tmp_path / "android_discovery.json").read_text())
    assert len(result["screens"]) == 2
    assert driver.page_source == START_XML
    assert evidence["navigation_action_count"] == 1
    # One step back to the screen: since run android_20261110_110821_90cd6d a single tap / Back is a cheap return,
    # counted apart from relaunch-and-replay recovery
    assert evidence["recovery_action_count"] + evidence["cheap_return_action_count"] == 1
    assert not result["discovery_issues"]


def test_remaining_controls_get_an_action_limit_reason(tmp_path, monkeypatch):
    driver = FakeDriver()
    driver.page_source = START_XML.replace('text="Delete account"', 'text="About"').replace('id/delete', 'id/about')
    start_xml = driver.page_source
    driver.back = lambda: setattr(driver, "page_source", start_xml)
    monkeypatch.setattr(android_pipeline, "create_session", lambda _: driver)
    monkeypatch.setattr(android_pipeline.time, "sleep", lambda _: None)
    state = _state(tmp_path)
    state["config"]["max_actions"] = 1
    result = android_pipeline.discovery_agent(state)
    assert any(u["reason"] == "Exploration action limit reached" for u in result["unvisited"])
    assert not any("recovery failed" in i["error"].lower() for i in result["discovery_issues"])


def test_installed_launch_waits_for_the_package_after_splash_handoff():
    caps = android.build_capabilities({"app_mode": "installed", "device_id": "fixture",
                                       "package_name": "com.example.demo", "app_activity": ".SplashActivity"})
    assert caps["appium:appWaitActivity"] == "*"
    assert caps["appium:appWaitPackage"] == "com.example.demo"
    assert caps["appium:appWaitDuration"] == 60000
    assert caps["appium:appActivity"] == ".SplashActivity"


def test_normalize_resolved_launcher_activity():
    assert android._normalize_resolved_activity(
        "com.saucelabs.mydemoapp.android",
        "com.saucelabs.mydemoapp.android/.view.activities.SplashActivity",
    ) == ".view.activities.SplashActivity"
    assert android._normalize_resolved_activity(
        "com.example.demo",
        "com.example.demo/com.example.demo.MainActivity",
    ) == "com.example.demo.MainActivity"


def test_launchable_activity_parses_resolve_activity_output(monkeypatch):
    class Result:
        stdout = (
            "priority=0 preferredOrder=0 match=0x108000\n"
            "com.saucelabs.mydemoapp.android/.view.activities.SplashActivity\n"
        )

    monkeypatch.setattr(android.shutil, "which", lambda _: "/usr/bin/adb")
    monkeypatch.setattr(android.subprocess, "run", lambda *_a, **_k: Result())
    assert android.launchable_activity(
        "emulator-5554", "com.saucelabs.mydemoapp.android"
    ) == ".view.activities.SplashActivity"


def test_recovery_reopens_only_the_target_when_back_exits_the_app(tmp_path, monkeypatch):
    class Driver(FakeDriver):
        activated = []

        def back(self):
            self.current_package = "com.android.launcher"

        def activate_app(self, package):
            self.activated.append(package)
            self.current_package = package
            self.page_source = START_XML

    driver = Driver()
    monkeypatch.setattr(android_pipeline, "create_session", lambda _: driver)
    monkeypatch.setattr(android_pipeline.time, "sleep", lambda _: None)
    state = _state(tmp_path)
    state["config"]["max_actions"] = 1
    result = android_pipeline.discovery_agent(state)
    assert driver.activated == ["com.example"]
    assert not result["discovery_issues"]
    assert driver.current_package == "com.example"


@pytest.mark.parametrize("fallback", [True, False])
def test_readiness_failure_is_bounded_and_fallback_is_explicit(tmp_path, monkeypatch, fallback):
    monkeypatch.setattr(android_pipeline, "android_environment", lambda _: {
        "ok": True, "devices": [{"device_id": "emulator-5554", "status": "device"}]})
    monkeypatch.setattr(llm, "llm_enabled", lambda: True)
    calls = []

    def fail(*_, **kwargs):
        calls.append(kwargs)
        raise llm.LLMError("Provider rejected the configured credential (401)")

    monkeypatch.setattr(llm, "ask_llm", fail)
    state = _state(tmp_path)
    state["config"]["allow_rules_fallback"] = fallback
    if fallback:
        result = android_pipeline.setup_agent(state)
        assert result["ai_unavailable"]
        assert "rules and templates" in result["ai_warnings"][0]
    else:
        with pytest.raises(android.AndroidEnvironmentError, match="AI readiness check failed"):
            android_pipeline.setup_agent(state)
    assert calls[0]["timeout_s"] == 20
    assert calls[0]["max_attempts"] == 1


def test_short_provider_probe_never_retries_or_changes_global_timeout(monkeypatch):
    from backend import cost, runctl
    monkeypatch.setattr(llm, "llm_enabled", lambda: True)  # independent of the user's persisted privacy policy
    monkeypatch.setattr(runctl, "stopping", lambda: False)
    monkeypatch.setattr(cost, "record", lambda *args: None)
    monkeypatch.setattr(llm.settings, "llm_timeout", 240)
    monkeypatch.setattr(llm, "llm_enabled", lambda: True)  # probe path even when env LLM_PROVIDER=none
    calls = []

    def timeout(*args, **kwargs):
        calls.append(kwargs)
        raise llm.LLMError("timed out") from requests.Timeout("simulated provider timeout")

    monkeypatch.setattr(llm, "_ask_once", timeout)
    with pytest.raises(llm.LLMError, match="timed out"):
        llm.ask_llm("OK", timeout_s=20, max_attempts=1)
    assert len(calls) == 1
    assert 0 < calls[0]["timeout_s"] <= 20
    assert llm.settings.llm_timeout == 240


def test_a_failed_probe_prevents_repeated_ai_calls_during_design(tmp_path, monkeypatch):
    from backend.android import extract_screen
    state = _state(tmp_path)
    state.update(ai_unavailable=True, ai_warnings=["AI readiness failed; rules used."], actions=[],
                 screens=[extract_screen(START_XML, "com.example", "emulator-5554", ".MainActivity")])
    monkeypatch.setattr(llm, "llm_enabled", lambda: True)
    monkeypatch.setattr(llm, "ask_llm", lambda *a, **k: pytest.fail("Failed AI must not be retried"))
    monkeypatch.setattr(llm, "ask_structured", lambda *a, **k: pytest.fail("Failed AI must not be retried"))
    state.update(android_design.design_cases(state))
    state.update(android_design.generate_scripts(state))
    assert state["ai_warnings"] == ["AI readiness failed; rules used."]
    assert list(state["script_sources"].values()) == ["template"]


def test_web_screen_names_distinguish_routes_without_exposing_query_data():
    class Driver:
        current_url = "https://example.test/login?token=not-for-display"
        capabilities = {}

        def execute_script(self, script):
            return {"url": self.current_url, "title": "The Internet", "elements": [], "total": 0}

    driver = Driver()
    config = {"device_id": "fixture", "start_url": "https://example.test/"}
    login = inspect_web(driver, config)
    driver.current_url = "https://example.test/dropdown"
    dropdown = inspect_web(driver, config)
    assert login["screen_name"] != dropdown["screen_name"]
    assert "/login" in login["screen_name"] and "/dropdown" in dropdown["screen_name"]
    assert "not-for-display" not in login["screen_name"]


def test_source_guide_and_fields_switch_without_starting_a_run(browser):
    context, page, errors, calls = studio(browser, viewport={"width": 1024, "height": 700})
    page.route("**/api/android/environment?*", lambda route: route.fulfill(json={
        "ok": True, "devices": [{"device_id": "emulator-5554", "status": "device"}]}))
    try:
        page.locator("#mobileModeBtn").click()
        expect(page.locator("#androidSourceHelp tr")).to_have_count(3)
        for mode, visible, hidden in [
            ("apk", "#androidApkField", "#androidUrlField"),
            ("installed", "#androidPackageField", "#androidApkField"),
            ("web", "#androidUrlField", "#androidActivityField"),
        ]:
            page.locator("#androidMode").select_option(mode)
            expect(page.locator(visible)).to_be_visible()
            expect(page.locator(hidden)).to_be_hidden()
        assert not errors
        assert not any("/api/mobile/runs" in call for call in calls)
    finally:
        context.close()


def test_ai_fallback_is_visible_in_live_execution(browser):
    context, page, errors, state = running_studio(browser)
    try:
        state["lines"] = ["::warning::AI readiness failed; rules and templates will be used for this run."]
        expect(page.locator(".warn").filter(has_text="AI readiness failed")).to_be_visible(timeout=10000)
        assert not errors
    finally:
        context.close()


@pytest.mark.parametrize("width,height", [(1024, 700), (390, 600)])
def test_android_execution_has_no_picture_guide_link(browser, width, height):
    context, page, errors, state = running_studio(browser, {"width": width, "height": height})
    try:
        expect(page.locator("#mobileForm")).to_be_hidden()
        expect(page.locator("#androidGuideBtn")).to_have_count(0)
        expect(page.locator('a[href="/static/android-testing-guide.html"]')).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        assert not errors
    finally:
        context.close()


def test_fallback_is_a_quality_risk_not_a_passing_provider_check():
    state = {"screens": [{"elements": []}], "ai_warnings": ["AI failed; rules used."]}
    gate = next(g for g in android_reporting.mobile_quality_gates(state) if g["id"] == "ai_provider")
    assert gate["status"] == "risk"
    assert "AI failed" in gate["detail"]
