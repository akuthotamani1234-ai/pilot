"""Phase 4: hybrid Android apps - each step runs in the context its locator belongs to (CSS -> the app's own WebView,
native locators -> native UI), switched automatically and recorded; a WebView that cannot be inspected is reported with
the exact reason; hybrid capabilities find a matching ChromeDriver. (No device here: a fake Appium driver; live
validation on a hybrid app is BLOCKED until a device / emulator and a hybrid test build are provided.)"""
import pytest

from backend.qa_contracts import Contract, Locator
from backend.qa_runtime import AndroidContractAdapter


class Element:
    def is_displayed(self):
        return True


def fake_driver(contexts=("NATIVE_APP", "WEBVIEW_com.example"), page_source="<hierarchy/>"):
    class Driver:
        current_context = "NATIVE_APP"
        current_url = "https://app.example.test/checkout"
        current_package = "com.example"
        found = []

        def __init__(self):
            self.contexts = list(contexts)
            self.page_source = page_source

        def find_elements(self, using, value):
            Driver.found.append((Driver.current_context, using, value))
            return [Element()]

        class _Switch:
            def context(self, name):
                Driver.current_context = name

        @property
        def switch_to(self):
            return Driver._Switch()
    return Driver()


def contract(steps):
    return Contract.model_validate({"allowed_origins": ["https://app.example.test"], "flows": [
        {"id": "f1", "title": "Hybrid checkout", "approved": True, "steps": steps}]})


NATIVE_TAP = {"action": "tap", "locator": {"strategy": "accessibility_id", "value": "Open shop"}}
WEB_TAP = {"action": "tap", "locator": {"strategy": "css", "value": "#continue"}}
CHECK = {"action": "assert_visible", "locator": {"strategy": "css", "value": "#total"}}
CONFIG = {"package_name": "com.example", "app_mode": "apk", "device_id": "emulator-5554"}


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    clock = [0.0]

    def tick():
        clock[0] += 1.0  # (a fake clock: a bounded wait ends at once instead of waiting real seconds)
        return clock[0]
    monkeypatch.setattr("backend.qa_runtime.time.sleep", lambda *_: None)
    monkeypatch.setattr("backend.qa_runtime.time.monotonic", tick)


def _adapter(driver, c):
    a = AndroidContractAdapter(driver, CONFIG, c)
    a.guard = lambda: None
    return a


def test_a_flow_without_context_steps_switches_per_locator_and_records_why():
    c = contract([NATIVE_TAP, WEB_TAP, CHECK])
    d = fake_driver()
    a = _adapter(d, c)
    assert a.auto_context
    a.find(Locator(strategy="accessibility_id", value="Open shop"))
    a.find(Locator(strategy="css", value="#continue"))
    a.find(Locator(strategy="accessibility_id", value="Done"))
    assert [ctx for ctx, *_ in type(d).found] == ["NATIVE_APP", "WEBVIEW_com.example", "NATIVE_APP"]
    assert [s["to"] for s in a.context_switches] == ["webview", "native"]
    assert "css locator belongs to the webview" in a.context_switches[0]["because"]


def test_a_flow_that_manages_contexts_itself_keeps_the_strict_rule():
    c = contract([{"action": "context", "value": "webview"}, WEB_TAP, CHECK])
    a = _adapter(fake_driver(), c)
    assert not a.auto_context
    with pytest.raises(ValueError, match="not native UI"):
        a.find(Locator(strategy="css", value="#continue"))


def test_a_webview_that_is_not_debuggable_is_reported_exactly():
    a = _adapter(fake_driver(contexts=("NATIVE_APP",),
                             page_source='<node class="android.webkit.WebView"/>'), None)
    with pytest.raises(RuntimeError, match="not debuggable.*setWebContentsDebuggingEnabled"):
        a.context("webview")
    b = _adapter(fake_driver(contexts=("NATIVE_APP",)), None)
    with pytest.raises(RuntimeError, match="No WebView of the selected app is open"):
        b.context("webview")
    c = _adapter(fake_driver(contexts=("NATIVE_APP", "WEBVIEW_com.example:1", "WEBVIEW_com.example:2")), None)
    with pytest.raises(RuntimeError, match="Several WebViews"):
        c.context("webview")


def test_hybrid_capabilities_find_a_matching_chromedriver_and_download_only_when_allowed(tmp_path, monkeypatch):
    from backend import android
    monkeypatch.delenv("QPILOT_CHROMEDRIVER", raising=False)
    monkeypatch.delenv("BLOWAI_CHROMEDRIVER", raising=False)
    monkeypatch.setenv("QPILOT_CHROMEDRIVER_DIR", str(tmp_path))
    monkeypatch.delenv("QPILOT_CHROMEDRIVER_AUTODOWNLOAD", raising=False)
    monkeypatch.setattr(android, "validate_mobile_config", lambda c: c)
    caps = android.build_capabilities({"app_mode": "installed", "package_name": "com.example",
                                       "app_activity": ".Main", "device_id": "emulator-5554"})
    assert caps["appium:chromedriverExecutableDir"] == str(tmp_path.resolve())
    assert "appium:chromedriverAutodownload" not in caps and caps["appium:nativeWebScreenshot"] is True
    monkeypatch.setenv("QPILOT_CHROMEDRIVER_AUTODOWNLOAD", "1")
    caps = android.build_capabilities({"app_mode": "installed", "package_name": "com.example",
                                       "app_activity": ".Main", "device_id": "emulator-5554"})
    assert caps["appium:chromedriverAutodownload"] is True


# ================================================================ Jira test cases on Android (the existing engine)
import json  # noqa: E402

from backend.atlassian import bridge  # noqa: E402
from tests.test_requirements_execution import _accept, api  # noqa: E402,F401


def test_jira_cases_run_on_android_through_the_existing_engine_tagged_per_case(api, monkeypatch):
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    body = {"strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1"]},
            "target": {"type": "android", "authorized": True, "android_mode": "installed",
                       "test_username": "u", "test_password": "p"}}
    pre = api.client.post("/api/requirements/executions/preflight", headers=api.H, json=body).json()
    assert {p["code"] for p in pre["problems"]} >= {"device", "package"} and not pre["ok"]
    assert "browser" not in {p["code"] for p in pre["problems"]}  # (no website probe for an installed app)
    started = {}

    async def fake_mobile(**kw):  # (the real one starts Appium on a device: none here)
        started.update(kw)
        api.server.jobs[515] = {"id": 515, "status": "running", "run": ""}
        return {"id": 515}
    monkeypatch.setattr(api.server, "start_mobile_run", fake_mobile)
    body["target"].update(device_id="emulator-5554", package_name="com.example.shop")
    r = api.client.post("/api/requirements/executions", headers=api.H, json=body)
    assert r.status_code == 200, r.text
    assert started["app_mode"] == "installed" and started["package_name"] == "com.example.shop"
    assert started["requirements"].startswith("[TC-QPL-2-1] ") and started["allow_rules_fallback"] is False
    assert started["interaction_testing"] is True and started["account_mode"] == "existing"


def test_an_android_runs_evidence_becomes_the_jira_result_of_each_tagged_case(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "refresh", lambda *a, **k: None)
    db = bridge.connect(tmp_path / "req.db")
    for cid in ("TC-A-1", "TC-A-2", "TC-A-3", "TC-A-4"):
        bridge._save(db, "t", {"id": cid, "tenant_id": "t", "requirement_id": "A", "status": "approved",
                               "fingerprint": cid, "version": 1, "kind": "positive", "title": cid,
                               "preconditions": [], "steps": ["x"], "expected": "y", "assertions": [],
                               "test_data_needs": [], "source_key": "jira:A", "source_version": 1,
                               "criterion_ids": ["A#AC-1"]}, "test")
    ex = bridge.plan(db, "t", ["TC-A-1", "TC-A-2", "TC-A-3", "TC-A-4"], "requirements",
                     {"type": "android", "url": ""})["execution"]
    run = tmp_path / "run"
    run.mkdir()
    (run / "android_interaction.json").write_text(json.dumps({
        "flows": [{"title": "Your test: [TC-A-1] add to cart", "meta": {"discovery_replay": "passed"},
                   "steps": [{"action": "tap"}, {"action": "assert_visible"}]},
                  {"title": "Your test: [TC-A-2] badge", "meta": {"discovery_replay": "failed twice: badge 0"}}],
        "tried": [{"check": "Your test: [TC-A-3] coupon", "outcome": "not automated",
                   "detail": "no journey matched this line with the observed controls"},
                  {"check": "Your test: [TC-A-1] add to cart", "outcome": "not automated"}]}))
    bridge.collect(db, "t", ex["id"], run)
    res = {r["test_case_id"]: r for r in bridge.results(db, "t", ex["id"])}
    assert res["TC-A-1"]["status"] == "Passed" and res["TC-A-2"]["status"] == "Failed"
    assert res["TC-A-3"]["status"] == "Not automated" and "no journey matched" in res["TC-A-3"]["reason"]
    assert res["TC-A-4"]["status"] == "Not run"  # (no evidence for it: never reported as passed)
