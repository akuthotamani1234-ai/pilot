"""Phase 7: iOS (Appium XCUITest) - config, capabilities, the environment a real run needs (each missing piece named),
the XCUI screen, steps with automatic native / WebView context, plans only over real controls, and the Jira path.
No Mac / simulator / device here: the driver is a fake; live iOS validation is BLOCKED (macOS + Xcode + a simulator or
device + Appium 2 with the xcuitest driver are needed)."""
import json

import pytest

from backend import ios
from tests.test_requirements_execution import _accept, api  # noqa: F401

XML = """<AppiumAUT><XCUIElementTypeApplication name="Shop" visible="true">
<XCUIElementTypeButton name="addToCart" label="Add to cart" visible="true" enabled="true" x="1" y="2" width="3" height="4"/>
<XCUIElementTypeStaticText name="cartBadge" label="1" value="1" visible="true"/>
<XCUIElementTypeButton name="hidden" label="Hidden" visible="false"/>
<XCUIElementTypeOther visible="true"/>
</XCUIElementTypeApplication></AppiumAUT>"""


def test_config_and_capabilities():
    with pytest.raises(ValueError, match="bundle id"):
        ios.validate({})
    with pytest.raises(ValueError, match="signing team"):
        ios.validate({"bundle_id": "com.example.shop", "real_device": True})
    c = ios.validate({"bundle_id": "com.example.shop", "platform_version": "17.4"})
    caps = ios.capabilities(c)
    assert caps["platformName"] == "iOS" and caps["appium:automationName"] == "XCUITest"
    assert caps["appium:bundleId"] == "com.example.shop" and "appium:xcodeOrgId" not in caps
    dev = ios.capabilities(ios.validate({"app_path": "/apps/Shop.ipa", "real_device": True,
                                         "udid": "00008110-001A2B3C4D5E6F70", "xcode_org_id": "ABCDE12345"}))
    assert dev["appium:xcodeOrgId"] == "ABCDE12345" and dev["appium:app"] == "/apps/Shop.ipa"


def test_every_missing_piece_of_the_ios_environment_is_named():
    problems = ios.environment_problems(ios.validate({"bundle_id": "com.example.shop"}),
                                        http_get=lambda url: (_ for _ in ()).throw(OSError("down")))
    text = " | ".join(problems)
    assert "needs macOS with Xcode" in text and "No Appium server answers" in text


def test_the_screen_lists_what_a_person_sees():
    controls = ios.screen(XML)
    assert [(c["type"], c["name"], c["label"]) for c in controls] == [("Button", "addToCart", "Add to cart"),
                                                                      ("StaticText", "cartBadge", "1")]


class El:
    def __init__(self, label="", value=""):
        self.label, self.value, self.clicked, self.typed = label, value, 0, ""

    def is_displayed(self):
        return True

    def click(self):
        self.clicked += 1

    def send_keys(self, v):
        self.typed += v

    def get_attribute(self, k):
        return {"label": self.label, "value": self.value, "name": ""}.get(k)


class Driver:
    def __init__(self):
        self.current_context = "NATIVE_APP"
        self.contexts = ["NATIVE_APP", "WEBVIEW_1234.1"]
        self.badge = El("0", "0")
        self.add = El("Add to cart")
        driver = self

        class Switch:
            def context(self, name):
                driver.current_context = name
        self.switch_to = Switch()

    def find_elements(self, by, value):
        if self.current_context.startswith("WEBVIEW"):
            return [El("Total $29.99")] if value == "#total" else []
        if value == "addToCart":
            return [self.add]
        if value == "cartBadge":
            self.badge.label = str(self.add.clicked)
            return [self.badge]
        return []

    def activate_app(self, b):
        pass

    def get_screenshot_as_file(self, path):
        open(path, "wb").write(b"png")


def test_steps_run_on_the_real_controls_switching_to_the_webview_when_needed(tmp_path):
    d = Driver()
    run = ios.IosRun(d, tmp_path, "com.example.shop")
    plan = ios.IosCase(case="TC-1", steps=[
        ios.IosStep(action="tap", target="addToCart"),
        ios.IosStep(action="assert_text", target="cartBadge", value="1"),
        ios.IosStep(action="assert_text", by="css", target="#total", value="$29.99")])
    rec = run.run_case(plan)
    assert rec["execution_status"] == "Passed" and rec["check_count"] == 2
    assert [s["to"] for s in run.context_switches] == ["WEBVIEW_1234.1"]
    assert rec["evidence"] == ["screenshots/TC-1.png"] and (tmp_path / "screenshots" / "TC-1.png").is_file()
    bad = run.run_case(ios.IosCase(case="TC-2", steps=[ios.IosStep(action="assert_text", target="cartBadge",
                                                                    value="5")]))
    assert bad["execution_status"] == "Failed" and "expected '5'" in bad["actual_result"]
    none = run.run_case(ios.IosCase(case="TC-3", not_possible="the app has no coupons"))
    assert none["execution_status"] == "Not run" and "no coupons" in none["skip_reason"]


def test_a_plan_may_only_use_controls_the_screen_shows():
    def ask(prompt, shape, **kw):
        return [ios.IosCase(case="TC-1", steps=[ios.IosStep(action="tap", target="addToCart"),
                                                ios.IosStep(action="assert_visible", target="cartBadge")]),
                ios.IosCase(case="TC-2", steps=[ios.IosStep(action="tap", target="checkoutNow")])]
    plans = {p.case: p for p in ios.plan_cases([{"id": "TC-1"}, {"id": "TC-2"}, {"id": "TC-3"}],
                                               ios.screen(XML), ask=ask)}
    assert len(plans["TC-1"].steps) == 2
    assert not plans["TC-2"].steps and "checkoutNow" in plans["TC-2"].not_possible
    assert "no iOS steps" in plans["TC-3"].not_possible


def test_a_jira_execution_on_ios_names_what_this_machine_lacks(api):
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    body = {"strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1"]},
            "target": {"type": "ios", "authorized": True, "ios": {"bundle_id": "com.example.shop",
                                                                   "appium_url": "http://127.0.0.1:9"}}}
    pre = api.client.post("/api/requirements/executions/preflight", headers=api.H, json=body).json()
    codes = {p["code"] for p in pre["problems"]}
    assert not pre["ok"] and "ios_environment" in codes
    assert any("macOS" in p["message"] or "Appium" in p["message"] for p in pre["problems"])
    r = api.client.post("/api/requirements/executions", headers=api.H, json=body)
    assert r.status_code == 409  # (refused before anything is created - BLOCKED, with the reason)
    assert json.dumps(r.json())
