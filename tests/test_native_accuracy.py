"""Native navigation, approved gestures and provider failures must retain real evidence."""

import pytest
import requests

from backend.android import extract_screen, find_unique, safe_navigation_elements
from backend.llm import _raise_with_reason
from backend.qa_contracts import Step
from backend.qa_runtime import AndroidContractAdapter


def test_bottom_navigation_does_not_promote_a_login_submission():
    xml = '<hierarchy><node><node class="android.widget.Button" content-desc="Home" clickable="true"/><node class="android.widget.Button" content-desc="Login" clickable="true"/><node class="android.widget.Button" content-desc="Forms" clickable="true"/></node><node class="android.widget.Button" content-desc="Login" clickable="true"/></hierarchy>'
    screen = extract_screen(xml, "com.example", "test")
    safe = safe_navigation_elements(screen)
    assert [e["accessibility_id"] for e in safe] == ["Home", "Login", "Forms"]
    assert screen["elements"][-1]["navigation_role"] == ""


def test_hidden_duplicate_does_not_make_a_unique_live_locator_ambiguous():
    class Element:
        def __init__(self, visible):
            self.visible = visible

        def is_displayed(self):
            return self.visible

    visible = Element(True)

    class Driver:
        def find_elements(self, *args):
            return [Element(False), visible]

    assert find_unique(Driver(), {"strategy": "accessibility_id", "value": "Example"}) is visible


def test_gestures_require_valid_direction_and_a_known_destination():
    loc = {"strategy": "accessibility_id", "value": "canvas"}
    with pytest.raises(ValueError):
        Step(action="swipe", locator=loc, value="diagonal")
    with pytest.raises(ValueError):
        Step(action="drag", locator=loc)
    with pytest.raises(ValueError):
        Step(action="tap", locator=loc, target=loc)
    assert Step(action="drag", locator=loc, target=loc).target.value == "canvas"


def test_android_gestures_use_live_element_bounds(monkeypatch):
    events = []

    class Driver:
        def execute_script(self, name, args):
            events.append((name, args))

    class Element:
        id = "observed-control"
        rect = {"x": 10, "y": 20, "width": 100, "height": 200}

    monkeypatch.setattr("backend.qa_runtime.time.sleep", lambda _: None)
    adapter = AndroidContractAdapter(Driver(), {}, None)
    adapter.swipe(Element(), "left")
    adapter.drag(Element(), Element())
    assert events[0] == ("mobile: swipeGesture", {"elementId": "observed-control", "direction": "left", "percent": 0.7})
    assert events[1][1]["endX"] == 60 and events[1][1]["endY"] == 120
    adapter.active = "webview"
    with pytest.raises(ValueError):
        adapter.drag(Element(), Element())


@pytest.mark.parametrize("error", ["model unavailable", {"message": "provider busy"}])
def test_provider_error_strings_and_objects_keep_the_original_reason(error):
    class Response:
        def raise_for_status(self):
            raise requests.HTTPError("400 failure", response=self)

        def json(self):
            return {"error": error}

    with pytest.raises(requests.HTTPError, match="model unavailable|provider busy"):
        _raise_with_reason(Response())


def test_unapproved_ai_fallback_stops_mobile_generation(tmp_path, monkeypatch):
    from backend import android_design as design, llm

    monkeypatch.setattr(llm, "llm_enabled", lambda: True)

    def fail(*args, **kwargs):
        raise llm.LLMError("unavailable")

    monkeypatch.setattr(llm, "ask_llm", fail)
    state = {
        "run_dir": str(tmp_path),
        "config": {"allow_rules_fallback": False},
        "test_cases": [{"id": "contract_example", "plan": [["assert_contract", ["example"]]]}],
    }
    with pytest.raises(llm.LLMError, match="fallback was not approved"):
        design.generate_scripts(state)
    assert not (tmp_path / "generated_tests" / "test_android_generated.py").exists()


def test_nested_scroll_alternates_regions_and_stays_bounded(monkeypatch):
    from backend.qa_contracts import Locator

    events = []

    class Driver:
        def execute_script(self, name, args):
            events.append(args)

    class Container:
        id = "scroll-container"
        rect = {"x": 0, "y": 50, "width": 1000, "height": 1500}

    adapter = AndroidContractAdapter(Driver(), {}, None)
    monkeypatch.setattr(adapter, "guard", lambda: None)
    monkeypatch.setattr(adapter, "find", lambda *args, **kwargs: object() if len(events) == 4 else None)
    monkeypatch.setattr("backend.qa_runtime.time.sleep", lambda _: None)
    assert adapter.scroll_to(Container(), Locator(strategy="accessibility_id", value="logo"), "up") == 4
    assert "elementId" in events[0] and "height" in events[1]
    assert events[1]["top"] >= Container.rect["y"]
    assert events[1]["top"] + events[1]["height"] <= Container.rect["y"] + Container.rect["height"]
    events.clear()
    monkeypatch.setattr(adapter, "find", lambda *args, **kwargs: None)
    from selenium.common.exceptions import NoSuchElementException

    with pytest.raises(NoSuchElementException, match="eight bounded"):
        adapter.scroll_to(Container(), Locator(strategy="accessibility_id", value="missing"), "up")
    assert len(events) == 8


def test_mobile_coverage_requires_execution_evidence(tmp_path):
    import json

    from backend.android_reporting import report

    state = {
        "run_dir": str(tmp_path),
        "run_id": "coverage_regression",
        "source": "Android fixture",
        "config": {"device_id": "test"},
        "results": [],
        "screens": [
            {
                "id": "S1",
                "package_name": "com.example",
                "screen_name": "Home",
                "elements": [
                    {"id": "E1", "type": "text", "text": "Home", "locators": [{"strategy": "text", "value": "Home"}]}
                ],
            }
        ],
        "test_cases": [
            {
                "id": "android_example",
                "kind": "ui",
                "title": "Home visible",
                "expected": "Home",
                "element_ids": ["E1"],
                "plan": [["assert_visible", ["E1"]]],
            }
        ],
    }
    report(state)
    coverage = json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["tested"] == 0 and coverage["planned"] == 1
    state["results"] = [{"id": "android_example", "outcome": "error", "error": "Device disconnected"}]
    report(state)
    assert json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))["tested"] == 0
    state["results"] = [{"id": "android_example", "outcome": "passed", "checks": 1}]
    report(state)
    assert json.loads((tmp_path / "coverage.json").read_text(encoding="utf-8"))["tested"] == 1


def test_repeated_product_locators_use_the_observed_row_label():
    xml = '<hierarchy><node><node class="android.widget.TextView" text="Backpack"/><node class="android.widget.TextView" resource-id="price" content-desc="Product Price" text="$29.99"/></node><node><node class="android.widget.TextView" text="Green backpack"/><node class="android.widget.TextView" resource-id="price" content-desc="Product Price" text="$29.99"/></node></hierarchy>'
    screen = extract_screen(xml, "com.example", "test")
    prices = [e for e in screen["elements"] if e["resource_id"] == "price"]
    assert all(e["locator_unique"] for e in prices)
    assert prices[0]["locators"][0]["strategy"] == "xpath"
    assert "@text='Backpack'" in prices[0]["locators"][0]["value"]
    assert "@text='Green backpack'" in prices[1]["locators"][0]["value"]


def test_recorded_unique_locator_fallback_precedes_healing(tmp_path, monkeypatch):
    from selenium.common.exceptions import NoSuchElementException

    from backend.android_design import normalize_screens
    from backend.android_runtime import MobileRuntime

    screen = extract_screen(
        '<hierarchy><node class="android.widget.TextView" content-desc="Product Title" text="Backpack"/></hierarchy>',
        "com.example",
        "test",
    )
    normalize_screens([screen])
    element = screen["elements"][0]
    element["locators"] = [
        {"strategy": "accessibility_id", "value": "ambiguous"},
        {"strategy": "text", "value": "Backpack"},
    ]

    class Live:
        def is_displayed(self):
            return True

    def find(driver, locator):
        if locator["value"] == "ambiguous":
            raise NoSuchElementException("Duplicate accessible label")
        return Live()

    monkeypatch.setattr("backend.android_runtime.find_unique", find)
    monkeypatch.setattr("backend.android_runtime.inspect_driver", lambda *args: screen)
    runtime = MobileRuntime(object(), {"device_id": "test"}, [screen], {}, tmp_path)
    runtime.assert_visible(element["id"])
    assert runtime.checks == 1 and runtime.locator_resolutions and not runtime.healing


def test_launch_readiness_waits_past_the_splash_screen(tmp_path, monkeypatch):
    from backend.android_runtime import MobileRuntime

    root = {
        "id": "home",
        "package_name": "com.example",
        "activity": ".Main",
        "screen_name": "Home",
        "fingerprint": "home",
        "elements": [{"id": "title", "visible": True, "text": "Home", "locators": [{"strategy": "text", "value": "Home"}]}],
    }
    loading = {**root, "activity": ".Splash", "screen_name": "Loading", "fingerprint": "splash"}
    screens = iter([loading, root, root])
    runtime = MobileRuntime(object(), {}, [root], {}, tmp_path)
    clock = {"seconds": 0}

    def inspect():
        clock["seconds"] += 10  # a cold UiAutomator hierarchy read can consume its idle wait
        return next(screens)

    monkeypatch.setattr(runtime, "_inspect", inspect)
    monkeypatch.setattr("backend.android_runtime.time.monotonic", lambda: clock["seconds"])
    monkeypatch.setattr("backend.android_runtime.time.sleep", lambda _: None)
    runtime.wait_for_start()


def test_open_drawer_excludes_background_and_allows_its_login_navigation():
    xml = '<hierarchy><node class="androidx.drawerlayout.widget.DrawerLayout"><node><node class="android.widget.Button" content-desc="View cart" clickable="true"/></node><node class="androidx.recyclerview.widget.RecyclerView" content-desc="Navigation menu"><node class="android.widget.Button" content-desc="Login Menu Item" text="Log In" clickable="true"/><node class="android.widget.Button" text="Reset App State" clickable="true"/></node></node></hierarchy>'
    screen = extract_screen(xml, "com.example", "test")
    safe = safe_navigation_elements(screen)
    assert screen["screen_name"] == "Navigation menu"
    # Drawer background (View cart) stays excluded; exhaustive explore allows Reset App State (pay-only block).
    assert [e["text"] for e in safe] == ["Log In", "Reset App State"]


def test_drawer_recovery_replays_from_home_before_pressing_back(tmp_path, monkeypatch):
    from backend import android_pipeline

    class Element:
        def __init__(self, driver, label):
            self.driver, self.label = driver, label

        def is_displayed(self):
            return True

        def is_enabled(self):
            return True

        def click(self):
            if self.label == "View menu":
                self.driver.reflowed = True
            self.driver.state = "menu" if self.label == "View menu" else "home" if self.label == "Catalog" else "about"

    class Driver:
        current_activity = ".Main"
        state = "home"
        exited = False
        reflowed = False

        @property
        def current_package(self):
            return "launcher" if self.exited else "com.example"

        @property
        def page_source(self):
            if self.state == "about":
                return '<hierarchy><node class="android.widget.TextView" text="About"/></hierarchy>'
            main = '<node class="android.widget.TextView" text="Home"/><node class="android.widget.Button" content-desc="View menu" clickable="true"/>'
            if self.reflowed:
                main += '<node class="android.view.ViewGroup"/>'
            menu = (
                '<node class="androidx.recyclerview.widget.RecyclerView" content-desc="Navigation menu"><node class="android.widget.Button" content-desc="Catalog" clickable="true"/><node class="android.widget.Button" content-desc="About" clickable="true"/></node>'
                if self.state == "menu"
                else ""
            )
            return (
                '<hierarchy><node class="androidx.drawerlayout.widget.DrawerLayout"><node>'
                + main
                + "</node>"
                + menu
                + "</node></hierarchy>"
            )

        def find_elements(self, by, value):
            return [Element(self, value)]

        def back(self):
            if self.state == "home":
                self.exited = True
            self.state = "home"

        def quit(self):
            pass

    driver = Driver()
    monkeypatch.setattr(android_pipeline, "create_session", lambda config: driver)
    monkeypatch.setattr("backend.android_pipeline.time.sleep", lambda _: None)
    state = {
        "run_dir": str(tmp_path),
        "run_id": "drawer",
        "config": {
            "device_id": "test",
            "package_name": "com.example",
            "max_actions": 40,
            "max_screens": 8,
            "max_depth": 2,
        },
        "log": [],
    }
    result = android_pipeline.discovery_agent(state)
    assert not driver.exited
    assert any(s["screen_name"] == "About" for s in result["screens"])
    assert result["discovery_issues"] == []


def test_recorded_product_row_locator_can_replay_safe_navigation(tmp_path, monkeypatch):
    from backend.android_design import normalize_screens
    from backend.android_runtime import MobileRuntime

    xml = '<hierarchy><node><node class="android.widget.TextView" text="Backpack"/><node class="android.widget.ImageView" resource-id="product" content-desc="Product Image" clickable="true"/></node><node><node class="android.widget.TextView" text="Green backpack"/><node class="android.widget.ImageView" resource-id="product" content-desc="Product Image" clickable="true"/></node></hierarchy>'
    screen = extract_screen(xml, "com.example", "test")
    normalize_screens([screen])
    product = next(e for e in screen["elements"] if e["resource_id"] == "product")
    clicked = []

    class Element:
        def is_enabled(self):
            return True

        def click(self):
            clicked.append(True)

    monkeypatch.setattr("backend.android_runtime.find_unique", lambda driver, locator: Element())
    monkeypatch.setattr("backend.android_runtime.time.sleep", lambda _: None)
    runtime = MobileRuntime(object(), {}, [screen], {}, tmp_path)
    monkeypatch.setattr(runtime, "_inspect", lambda: screen)
    runtime.tap(product["id"])
    assert clicked == [True]


def test_discovery_waits_past_a_noninteractive_splash(tmp_path, monkeypatch):
    from backend import android_pipeline
    from backend.android import inspect_driver
    from tests.test_android_pipeline import FakeDriver, _state

    driver = FakeDriver()
    loading = extract_screen(
        '<hierarchy><node class="android.widget.TextView" text="Loading..."/></hierarchy>',
        "com.example",
        "test",
        ".Splash",
    )
    calls = []

    def inspect(live, config):
        calls.append(True)
        return loading if len(calls) == 1 else inspect_driver(live, config)

    monkeypatch.setattr(android_pipeline, "create_session", lambda config: driver)
    monkeypatch.setattr(android_pipeline, "inspect_driver", inspect)
    monkeypatch.setattr("backend.android_pipeline.time.sleep", lambda _: None)
    result = android_pipeline.discovery_agent(_state(tmp_path))
    assert result["screens"] and result["screens"][0]["activity"] == ".MainActivity"
    assert all(s["screen_name"] != "Loading..." for s in result["screens"])
