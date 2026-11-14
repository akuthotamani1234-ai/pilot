"""Test mode ("test everything except checkout"): the never-press rules, test-mode flows, AI journeys and the earlier
fixes that had no test yet.

Runs: runs/android_20261109_170355_a7b3dd (My Demo App: the AI wrapped its journeys in {"user_journeys": [...]} and
was rejected with "Input should be a valid list"; the budget went to rating stars start1..start5 instead of the menu).
"""

import json
import time
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter

from backend import android_interact, android_pipeline
from backend.android import RISKY_ACTION, AndroidEnvironmentError, repeat_family, validate_mobile_config
from backend.qa_contracts import IRREVERSIBLE, never_in_test_mode, parse_contract, protected
from tests.android_fake_site import BASE, FakeElement, FakeShop, node
from tests.test_android_real_tester import FakeApp, _session


@pytest.fixture(autouse=True)
def _virtual_clock(monkeypatch):
    offset, real = [0.0], time.monotonic
    monkeypatch.setattr(time, "sleep", lambda seconds: offset.__setitem__(0, offset[0] + seconds))
    monkeypatch.setattr(time, "monotonic", lambda: real() + offset[0])


# ------------------------------------------------------------------ 1. what is never pressed, in every mode

NEVER = ["Checkout", "Proceed To Checkout", "Place order", "Place Order", "Confirm order", "Buy now", "Pay now",
         "Purchase", "Payment", "Delete account", "Crash app", "Force close", "Share"]
ALLOWED_IN_TEST_MODE = ["Remove", "Remove from cart", "Log out", "Sort by", "My orders", "Orders", "Subscribe",
                        "Add to cart", "Update shopping cart", "Contact us", "Send message", "Email a friend"]


@pytest.mark.parametrize("words", NEVER)
def test_checkout_payment_and_the_never_list_are_blocked_in_every_mode(words):
    assert never_in_test_mode(words) and never_in_test_mode(words, native=True)  # test mode, web and app
    assert protected(words, test_mode=False)  # approved flows outside test mode (IRREVERSIBLE)
    assert RISKY_ACTION.search(words) or IRREVERSIBLE.search(words)  # safe discovery
    assert android_interact.NEVER_TAP.search(words)


@pytest.mark.parametrize("words", ALLOWED_IN_TEST_MODE)
def test_undoable_shop_actions_are_allowed_only_in_test_mode(words):
    assert never_in_test_mode(words) == ""
    if IRREVERSIBLE.search(words):
        assert protected(words, test_mode=False)  # outside test mode the stricter rule is unchanged


def test_the_never_reason_is_specific():
    assert "checkout" in never_in_test_mode("Proceed To Checkout")
    assert "account" in never_in_test_mode("Delete my account")
    assert "crash" in never_in_test_mode("Crash app (debug)")
    assert "password" in never_in_test_mode("Change password")
    assert never_in_test_mode("Call us") and never_in_test_mode("Send SMS")
    # A native app's camera / contacts are other apps; a website's "Contact us" is its own page
    assert never_in_test_mode("Contact us", native=True) and not never_in_test_mode("Contact us", native=False)


def test_crash_and_force_close_buttons_are_never_user_like_candidates():
    screen = {"elements": [{"id": f"e{i}", "visible": True, "enabled": True, "clickable": True, "text": text,
                            "locators": [{"strategy": "text", "value": text}]}
                           for i, text in enumerate(["Crash app (debug)", "Force close", "Add To Cart"])]}
    assert [e["text"] for e in android_interact.reversible_candidates(screen)] == ["Add To Cart"]


# ------------------------------------------------------------------ 2. flows made in test mode

def _flow(steps, **contract):
    return {"version": 1, "test_environment": True, "flows": [{"id": "f", "title": "t", "approved": True,
                                                               "steps": steps}], **contract}


REMOVE = [{"action": "tap", "locator": {"strategy": "css", "value": "button.remove-btn"}, "purpose": "test_form"},
          {"action": "assert_visible", "locator": {"strategy": "css", "value": "div.empty"}}]


def test_a_remove_tap_is_valid_only_in_a_test_mode_contract():
    with pytest.raises(ValueError):
        parse_contract(_flow(REMOVE))
    assert parse_contract(_flow(REMOVE, test_mode=True)).test_mode
    with pytest.raises(ValueError):  # test mode needs an approved test environment
        parse_contract({**_flow(REMOVE, test_mode=True), "test_environment": False})
    checkout = [{"action": "tap", "locator": {"strategy": "css", "value": "#checkout"}, "purpose": "test_form"}]
    with pytest.raises(ValueError):  # checkout stays blocked even in test mode
        parse_contract(_flow(checkout + REMOVE[1:], test_mode=True))


def test_open_steps_stay_inside_the_approved_origins():
    good = [{"action": "open", "value": BASE + "/cart"}, REMOVE[1]]
    assert parse_contract(_flow(good, test_mode=True, allowed_origins=[BASE]))
    with pytest.raises(ValueError):
        parse_contract(_flow([{"action": "open", "value": "https://evil.example/x"}, REMOVE[1]], test_mode=True,
                             allowed_origins=[BASE]))
    with pytest.raises(ValueError):
        parse_contract(_flow([{"action": "open", "value": "file:///c:/x"}, REMOVE[1]]))


def test_test_mode_flows_run_only_when_the_run_is_in_test_mode_again():
    config = {"app_mode": "web", "device_id": "emulator-5554", "start_url": BASE + "/",
              "qa_contract": _flow(REMOVE, test_mode=True)}
    with pytest.raises(AndroidEnvironmentError, match="test-mode box"):
        validate_mobile_config(config)
    assert validate_mobile_config({**config, "interaction_testing": True})["qa_contract"]["test_mode"]


def test_zero_soft_limits_keep_until_exhausted_and_explicit_limits_are_validated():
    config = validate_mobile_config({"app_mode": "web", "device_id": "emulator-5554", "start_url": BASE + "/"})
    assert (config["max_interactions"], config["interaction_timeout_s"]) == (0, 0)
    assert (config["bot_check_wait_s"], config["human_wait_s"]) == (30, 180)
    with pytest.raises(AndroidEnvironmentError):
        validate_mobile_config({**config, "max_interactions": 501})
    with pytest.raises(AndroidEnvironmentError):
        validate_mobile_config({**config, "interaction_timeout_s": 3601})


def test_feature_coverage_parses_test_mode_flows():
    """A kept 'Remove from cart' flow used to fail the report: features.json parsed it with the strict rules."""
    from backend.android_features import feature_matrix
    flows = [{"flow": parse_contract(_flow(REMOVE, test_mode=True)).flows[0].model_dump(mode="json"), "meta": {}}]
    cases = android_interact.auto_cases(flows)
    matrix = feature_matrix({"test_cases": cases, "results": [], "screens": [], "config": {}, "auto_flows": flows})
    assert matrix["functional_checks"]["configured"] == 1


# ------------------------------------------------------------------ 3. AI journeys

def _journeys(shape_data, tmp_path):
    session, _ = _session(FakeApp("shop"), tmp_path)

    def ask(_prompt, shape):  # what llm.ask_structured does with the AI's answer
        return TypeAdapter(shape).validate_python(shape_data)
    session.ai_journeys(ask)
    return session


JOURNEY = {"title": "Add an item and see the badge", "start": "S1",
           "steps": [{"action": "tap", "element": "E2"}, {"action": "assert_visible", "element": "E1"}]}


@pytest.mark.parametrize("answer", [{"journeys": [JOURNEY]}, {"user_journeys": [JOURNEY]}, [JOURNEY],
                                    {"result": [JOURNEY, {"title": "broken"}]}])
def test_ai_journeys_are_accepted_wrapped_or_bare_and_bad_items_are_left_out(answer, tmp_path):
    session = _journeys(answer, tmp_path)
    assert any(t["check"].startswith("Journey: Add an item") for t in session.tried)


def test_an_ai_answer_without_any_valid_journey_is_rejected_and_the_rules_stand(tmp_path):
    with pytest.raises(ValueError):
        _journeys({"journeys": [{"title": "no steps"}]}, tmp_path)
    session, _ = _session(FakeApp("shop"), tmp_path)
    session.run(ask=lambda _p, _s: (_ for _ in ()).throw(ValueError("bad answer")))
    assert any(r["name"] == "AI journeys" and r["status"] == "not tested" for r in session.coverage)
    assert any(item["meta"]["category"] == "user_action" for item in session.flows)  # rule-based checks kept


# ------------------------------------------------------------------ 4. earlier fixes, now tested

def test_repeat_family_groups_unlabelled_look_alikes_only():
    stars = [{"class_name": "android.widget.ImageView", "resource_id": f"com.x:id/start{i}IV"} for i in range(1, 6)]
    assert len({repeat_family(star) for star in stars}) == 1
    assert repeat_family({**stars[0], "accessibility_id": "Rate 1 star"}) is None
    assert repeat_family({**stars[0], "navigation_role": "menu_item"}) is None


def _discovery(tmp_path, monkeypatch, test_build):
    xml = ('<hierarchy>'
           '<node class="android.widget.Button" resource-id="com.x:id/about" text="About" clickable="true" bounds="[0,0][9,9]"/>'
           '<node class="android.widget.Button" resource-id="com.x:id/products" text="Products" clickable="true" bounds="[0,10][9,19]"/>'
           '<node class="android.widget.Button" resource-id="com.x:id/login" text="Open login screen" clickable="true" bounds="[0,20][9,29]"/>'
           '</hierarchy>')

    class Driver:
        current_package, current_activity, page_source, capabilities = "com.x", ".Main", xml, {}

        def find_elements(self, _by, _value):
            return [SimpleNamespace(is_displayed=lambda: True, is_enabled=lambda: True, click=lambda: None)]

        def execute_script(self, *_args):
            return []

        def activate_app(self, _package):
            pass

        def terminate_app(self, _package):
            pass

        def back(self):
            pass

        def quit(self):
            pass

    monkeypatch.setattr(android_pipeline, "create_session", lambda _config: Driver())
    state = {"config": {"app_mode": "apk", "package_name": "com.x", "device_id": "emulator-5554", "max_actions": 5,
                        "max_screens": 5, "interaction_testing": test_build, "max_interactions": 0,
                        "interaction_timeout_s": 30}, "run_dir": str(tmp_path), "log": []}
    return [a["label"] for a in android_pipeline.discovery_agent(state)["actions"]]


def test_test_build_mode_reaches_the_login_screen_first(tmp_path, monkeypatch):
    assert _discovery(tmp_path, monkeypatch, True)[0] == "Open login screen"
    assert _discovery(tmp_path, monkeypatch, False)[0] == "About"


def test_scrolling_to_a_control_is_not_counted_as_its_effect(tmp_path):
    session, screens = _session(FakeApp("shop"), tmp_path)
    seen = []
    session.perform = lambda steps: seen.append([s["action"] for s in steps])
    pictures = iter(["after scrolling", "after the tap"])
    session.device.observe = lambda: next(pictures)
    session.device.go_to = lambda _screen: "start"
    scroll = {"action": "scroll_to", "locator": {"strategy": "id", "value": "list"},
              "target": {"strategy": "id", "value": "x"}, "value": "up"}
    before, after = session.observe_after(screens[0], [scroll, {"action": "tap"}])
    assert (before, after) == ("after scrolling", "after the tap") and seen == [["scroll_to"], ["tap"]]


def test_a_menu_button_on_every_screen_is_not_the_screens_anchor():
    menu = {"id": "m", "class_name": "Button", "accessibility_id": "View menu", "visible": True, "enabled": True,
            "locators": [{"strategy": "accessibility_id", "value": "View menu"}], "bounds": "[0,0][9,9]"}
    title = {"id": "t", "class_name": "TextView", "text": "Products", "visible": True, "enabled": True,
             "resource_id": "com.x:id/title", "locators": [{"strategy": "resource_id", "value": "com.x:id/title"}],
             "bounds": "[0,50][9,59]"}
    screen = {"screen_name": "Catalog", "elements": [menu, title]}
    assert android_interact.anchor(screen)["id"] == "m"
    assert android_interact.anchor(screen, {android_interact.family(menu)})["id"] == "t"


# ------------------------------------------------------------------ 5. the runtime in Android Chrome

def _adapter(shop):
    from backend.qa_runtime import AndroidContractAdapter
    config = {"app_mode": "web", "start_url": BASE + "/", "device_id": "emulator-5554", "interaction_testing": True}
    return AndroidContractAdapter(shop, config, parse_contract(_flow(REMOVE, test_mode=True)))


def test_a_web_check_box_reports_its_ticked_state():
    shop = FakeShop()
    adapter = _adapter(shop)
    box = FakeElement(shop, node("#agree", "input", input=True, type="checkbox"))
    assert adapter.checked(box) is False
    shop.fields["#agree"] = True
    assert adapter.checked(box) is True
    with pytest.raises(ValueError):
        adapter.checked(FakeElement(shop, node("#q", "input", input=True, type="text")))
    assert adapter.test_mode  # the run itself is in test mode


def test_an_assert_visible_waits_for_a_control_that_appears_after_a_request():
    from backend.qa_runtime import ContractRuntime

    class Slow:
        default_context = "webview"

        def __init__(self):
            self.calls = 0

        def guard(self):
            pass

        def find(self, _locator, optional=False):
            self.calls += 1
            return "dialog" if self.calls > 3 else None

        def visible(self, element):
            return element == "dialog"

        def context(self, _target):
            pass

    contract = _flow([{"action": "assert_visible", "locator": {"strategy": "css", "value": "div.dialog"}}])
    runtime = ContractRuntime(Slow(), contract, {"secrets": {}, "databases": {}})
    runtime.execute("f")
    assert runtime.checks == 1


def test_a_page_recorded_by_test_mode_opens_by_its_address_in_the_final_run(tmp_path):
    from backend.android_design import normalize_screens
    from backend.android_runtime import MobileRuntime
    from backend.android_web import inspect_web

    shop = FakeShop()
    config = {"app_mode": "web", "start_url": BASE + "/", "device_id": "emulator-5554", "interaction_testing": True}
    home = inspect_web(shop, config)
    shop.get(BASE + "/computers")
    computers = {**inspect_web(shop, config), "open_by_url": True}
    screens = normalize_screens([home, computers])
    shop.get(BASE + "/")
    runtime = MobileRuntime(shop, config, screens, {}, tmp_path)
    runtime.open_screen(computers["id"])
    assert shop.path == "/computers" and runtime.steps[-1]["text"].startswith("Open ")


def test_the_registered_account_reaches_the_final_runs_secrets():
    saved = {"BLOWAI_SECRET_AUTO_ACCOUNT_USERNAME": "qa1@example.com", "BLOWAI_SECRET_TEST_PASSWORD": "not-allowed"}
    secrets = android_interact.flow_secrets({}, saved)
    assert secrets["BLOWAI_SECRET_AUTO_ACCOUNT_USERNAME"] == "qa1@example.com"
    assert "BLOWAI_SECRET_TEST_PASSWORD" not in secrets  # only generated values come from the saved file


def test_the_web_conftest_starts_each_test_mode_flow_as_a_first_time_visitor():
    from pathlib import Path
    template = Path(android_pipeline.__file__).with_name("templates") / "android_conftest.py"
    source = template.read_text(encoding="utf-8")
    web_branch = source[source.index('CONFIG.get("app_mode") == "web" and case.get("reset_app_data")'):]
    assert web_branch.index("reset_site_data(driver, CONFIG)") < web_branch.index('driver.get(CONFIG["start_url"])')
    assert json.dumps  # (keeps the json import used by helpers above)
