"""Real DOM extraction and shared-pipeline contracts for Android Chrome."""
import json

import pytest
from fastapi.testclient import TestClient

from backend import android, server
from backend.android_web import DOM_SCRIPT, inspect_web
from backend.qa_contracts import parse_contract
from backend.qa_runtime import AndroidContractAdapter, ContractRuntime
from tests.test_android_api import DEVICE_ENVIRONMENT, FakeProcess, FakeThread
from tests.test_results_layout import browser as shared_browser


@pytest.fixture(scope="module")
def browser():
    yield from shared_browser.__wrapped__()


def config(**overrides):
    return {"app_mode": "web", "device_id": "emulator-5554", "start_url": "https://example.test/", **overrides}


def test_chrome_capabilities_are_idempotent_and_do_not_launch_a_native_app(monkeypatch):
    monkeypatch.setattr(android, "_managed_web_chromedriver", lambda config: None)
    normalized = android.validate_mobile_config(config())
    caps = android.build_capabilities(normalized)
    assert caps["browserName"] == "Chrome"
    assert "appium:appPackage" not in caps and "appium:app" not in caps
    assert normalized["package_name"] == "com.android.chrome"


def test_session_start_has_a_separate_bounded_timeout(monkeypatch):
    from appium import webdriver

    clients = []

    class Lock:
        def __init__(self, device):
            pass

        def __enter__(self):
            pass

        def __exit__(self, *args):
            pass

    class Driver:
        def quit(self):
            pass

    def remote(url, options, client_config):
        assert client_config.timeout == 300
        assert client_config.extra_headers is None  # Do not change Selenium's shared header dictionary.
        assert url.extra_headers == {"X-Appium-Is-Sensitive": "1"}
        clients.append(client_config)
        return Driver()

    monkeypatch.setattr(android, "DeviceLock", Lock)
    monkeypatch.setattr(webdriver, "Remote", remote)
    driver = android.create_session({"app_mode": "installed", "package_name": "com.example.demo", "device_id": "fixture"})
    assert clients[0].timeout == 60
    driver.quit()


def test_installed_driver_metadata_needs_registration_and_a_real_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setenv("APPIUM_HOME", str(tmp_path))
    package = tmp_path / "node_modules/appium-uiautomator2-driver"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "appium-uiautomator2-driver", "version": "8.7.3",
        "main": "index.js", "appium": {"driverName": "uiautomator2"}}))
    (package / "index.js").write_text("export {}")
    assert android._uiautomator_installation() is None
    manifest = tmp_path / "node_modules/.cache/appium/extensions.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("drivers:\n  uiautomator2:\n    pkgName: appium-uiautomator2-driver\nplugins: {}\n")
    assert "8.7.3" in android._uiautomator_installation()
    (package / "index.js").unlink()
    assert android._uiautomator_installation() is None


def test_only_the_known_system_ui_wait_dialog_can_be_recovered():
    class Button:
        clicked = 0

        def is_displayed(self):
            return True

        def click(self):
            self.clicked += 1

    class Driver:
        button = Button()

        def find_elements(self, by, value):
            assert by == "id" and value == "android:id/aerr_wait"
            return [self.button]

    driver = Driver()
    xml = '''<hierarchy><node package="android" text="System UI isn't responding"/>
        <node package="android" resource-id="android:id/aerr_wait" text="Wait"/></hierarchy>'''
    assert android.recover_system_ui(driver, xml)
    assert driver.button.clicked == 1
    assert android.recover_system_ui(driver, xml)
    with pytest.raises(android.AndroidEnvironmentError, match="repeatedly"):
        android.recover_system_ui(driver, xml)
    assert not android.recover_system_ui(driver, '<hierarchy><node package="android" text="Allow access?"/></hierarchy>')
    assert not android.recover_system_ui(driver, '''<hierarchy>
        <node package="com.example" text="System UI isn't responding"/>
        <node package="com.example" resource-id="android:id/aerr_wait" text="Wait"/></hierarchy>''')
    assert driver.button.clicked == 2


@pytest.mark.parametrize("url", ["", "file:///tmp/a", "https://user:password@example.test", "http://169.254.169.254/"])
def test_chrome_rejects_unsafe_or_missing_targets(url):
    with pytest.raises(android.AndroidEnvironmentError):
        android.validate_mobile_config(config(start_url=url))


def test_android_chrome_endpoint_uses_the_existing_worker_and_status_api(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RUNS", tmp_path)
    monkeypatch.setattr(server, "jobs", {})
    monkeypatch.setattr(server, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(server.threading, "Thread", FakeThread)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: FakeProcess())
    monkeypatch.setattr(android, "android_environment", lambda *a: DEVICE_ENVIRONMENT)
    with TestClient(server.app, base_url="http://127.0.0.1") as client:
        response = client.post("/api/mobile/runs", headers={"X-Agentic-QA": "1"},
                               data={**config(), "authorized": "true", "llm_provider": "none"})
        assert response.status_code == 200, response.json()
        job = response.json()
        saved = json.loads((tmp_path / job["run"] / ".private/android_config.json").read_text())
        assert saved["start_url"] == "https://example.test/"
        assert saved["app_mode"] == "web" and job["target_type"] == "android"
        assert "Android Chrome" in job["source"]


def test_dom_inventory_lists_inputs_dropdowns_and_safe_navigation_without_input_values(browser):
    context = browser.new_context()
    page = context.new_page()
    page.route("https://example.test/**", lambda r: r.fulfill(content_type="text/html", body='''
        <title>Example</title><h1>Dashboard</h1><a href="/products">Products</a>
        <a href="https://outside.test/">Other site</a><a href="/delete-all">More</a>
        <input id="password" type="password" value="PRIVATE-INPUT-CONTENT">
        <select id="choice"><option value="one">First</option><option value="two">Second</option></select>
        <button aria-expanded="false" type="button">Categories</button>
        <form><button type="submit">Search</button></form><a download href="/file">Download file</a>
        <a href="#main" style="position:absolute;left:-5000px">Skip to content</a>
        <details><summary>More menu</summary><button>About</button></details>'''))
    page.goto("https://example.test/")

    class Driver:
        current_url = page.url
        capabilities = {}

        def execute_script(self, script):
            return page.evaluate("script => new Function(script)()", script)

    try:
        screen = inspect_web(Driver(), android.validate_mobile_config(config()))
        assert "PRIVATE-INPUT-CONTENT" not in json.dumps(screen)
        dropdown = next(e for e in screen["elements"] if e["resource_id"] == "choice")
        assert len(dropdown["options"]) == 2 and dropdown["input_capable"]
        safe = android.safe_navigation_elements(screen)
        assert any(e["text"] == "Products" for e in safe)
        assert any(e["text"] == "Categories" for e in safe)
        # Pay-only never-press: /delete-all ("More") may be explored; off-site/submit/download/skip stay out.
        assert any(e["text"] == "More" for e in safe)
        assert not any(e["text"] in ("Other site", "Search", "Download file", "Skip to content") for e in safe)
        for node in screen["elements"]:
            assert page.locator(node["locators"][0]["value"]).count() == 1
        assert page.evaluate("script => new Function(script)()", DOM_SCRIPT)["title"] == "Example"
    finally:
        context.close()


def test_external_origin_is_rejected_before_any_dom_read():
    class Driver:
        current_url = "https://outside.test/"

        def execute_script(self, script):
            pytest.fail("External DOM must not be inspected")

    with pytest.raises(android.AndroidEnvironmentError, match="approved"):
        inspect_web(Driver(), config())


def test_mobile_web_contract_stays_in_browser_context():
    contract = parse_contract({"test_environment": True, "flows": [{"id": "title", "title": "Title",
        "approved": True, "steps": [{"action": "assert_screen", "value": "Example"}]}]})

    class Driver:
        current_url = "https://example.test/"
        title = "Example"

    adapter = AndroidContractAdapter(Driver(), config(), contract)
    runtime = ContractRuntime(adapter, contract.model_dump())
    runtime.execute("title")
    assert runtime.checks == 1 and adapter.active == "webview"


def test_chrome_field_readback_uses_current_dom_property_not_initial_attribute():
    class Element:
        value = ""

        def clear(self):
            self.value = ""

        def send_keys(self, value):
            self.value = value

        def get_attribute(self, name):
            return None  # A filled input can still have no HTML value attribute.

        def get_property(self, name):
            return self.value if name == "value" else "INPUT"

    adapter = AndroidContractAdapter(None, config(), parse_contract())
    element = Element()
    adapter.fill(element, "demo")
    assert element.value == "demo" and adapter.input_sensitive(element)


def test_result_assertion_waits_for_the_new_page_instead_of_asserting_the_old_heading(monkeypatch):
    from backend import qa_runtime

    class Adapter:
        lookups = 0

        def guard(self):
            pass

        def find(self, locator):
            self.lookups += 1
            return "old" if self.lookups == 1 else "new"

        def input_sensitive(self, element):
            return False

        def text(self, element):
            return "Login Page" if element == "old" else "Secure Area"

        def context(self, target):
            pass

    monkeypatch.setattr(qa_runtime.time, "sleep", lambda seconds: None)
    adapter = Adapter()
    contract = {"test_environment": True, "flows": [{"id": "result", "title": "Result", "approved": True,
        "steps": [{"action": "assert_text", "locator": {"strategy": "css", "value": "h2"}, "value": "Secure Area"}]}]}
    runtime = ContractRuntime(adapter, contract)
    runtime.execute("result")
    assert runtime.checks == 1 and adapter.lookups == 2


def test_truncated_or_container_text_does_not_become_an_exact_label_assertion(monkeypatch):
    from backend import llm
    from backend.android_design import design_cases

    monkeypatch.setattr(llm, "llm_enabled", lambda: False)
    node = {"id": "first", "type": "text", "text": "A partial container...", "text_comparable": False,
            "visible": True, "locators": [{"strategy": "css", "value": "#container"}]}
    state = {"config": config(), "screens": [{"id": "s", "fingerprint": "f", "package_name": "com.android.chrome",
             "screen_name": "Example", "activity": "url", "elements": [node]}]}
    result = design_cases(state)
    assert not any(method == "assert_text" for case in result["test_cases"] for method, args in case.get("plan", []))


def test_validator_does_not_echo_inline_password():
    with TestClient(server.app, base_url="http://127.0.0.1") as client:
        response = client.post("/api/contracts/validate", headers={"X-Agentic-QA": "1"}, json={"contract": {
            "flows": [{"id": "bad", "title": "Bad", "steps": [
                {"action": "fill", "locator": {"strategy": "css", "value": "#password"}, "value": "DO-NOT-ECHO"},
                {"action": "assert_visible", "locator": {"strategy": "css", "value": "h1"}}]}]}})
        assert response.status_code == 400
        assert "DO-NOT-ECHO" not in response.text
