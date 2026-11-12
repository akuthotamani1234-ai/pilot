"""Test mode for a native app test build ("every feature except checkout"), offline, against a fake app shaped like the
Sauce Labs My Demo App (tests/android_fake_app.py), through the real discovery pipeline.

Lessons from runs/android_20261109_170355_a7b3dd (27 min: 18 exploring vs 50 recovery actions, the drawer items never
opened, 15 of 18 actions on rating stars, tests were navigation replays and visibility checks) and
runs/android_20261109_181718_321078 (scrolling "left the verified screen", "Drawing opens content outside the app",
a false "Login with a wrong password was accepted", generic protected-rule reasons).
"""

import json
from pathlib import Path

import pytest

from backend import android_pipeline
from backend.android import extract_screen, inspect_driver, safe_navigation_elements
from backend.android_runtime import same_screen
from backend.qa_contracts import never_in_test_mode
from tests.android_fake_app import IME, PACKAGE, PERMISSIONS, FakeDemoApp
from tests.test_android_site import VirtualClock

FIXTURE = Path(__file__).parent / "fixtures" / "mda_screens_20261109_170355.json"
CONFIG = {"app_mode": "installed", "package_name": PACKAGE, "device_id": "emulator-5554", "interaction_testing": True,
          "max_actions": 60, "max_screens": 40, "discovery_timeout_s": 600, "max_depth": 3, "max_interactions": 400,
          "interaction_timeout_s": 3600}


def explore(tmp_path, app, **config):
    with VirtualClock():
        original = android_pipeline.create_session
        android_pipeline.create_session = lambda _config: app
        try:
            state = {"config": {**CONFIG, **config}, "run_dir": str(tmp_path), "log": []}
            return {**state, **android_pipeline.discovery_agent(state)}
        finally:
            android_pipeline.create_session = original


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    app = FakeDemoApp()
    folder = tmp_path_factory.mktemp("app")
    result = explore(folder, app)
    return {"app": app, "result": result, "dir": folder, "titles": [i["flow"]["title"] for i in result["auto_flows"]],
            "rows": result["interaction"]["coverage"], "tried": result["interaction"]["tried"]}


def flow(run, start):
    return next(item["flow"] for item in run["result"]["auto_flows"] if item["flow"]["title"].startswith(start))


# ------------------------------------------------------------------ 1. discovery spends its time exploring

def test_the_real_my_demo_app_screens_offer_the_menu_first_and_no_rating_stars():
    screens = {s["screen_name"]: s for s in json.loads(FIXTURE.read_text(encoding="utf-8"))}
    names = lambda screen: [e.get("text") or e.get("accessibility_id") for e in safe_navigation_elements(screen)]  # noqa: E731
    assert names(screens["Products"]) == ["View menu", "View cart", "Product Image"]
    assert names(screens["Navigation menu"]) == ["Catalog", "WebView", "Drawing", "About", "FingerPrint",
                                                 "Virtual USB", "Log In"]


def test_a_list_of_product_pictures_is_a_list_even_without_a_list_widget():
    xml = ('<hierarchy><node><node class="android.widget.TextView" text="Backpack"/><node class="android.widget.'
           'ImageView" resource-id="product" content-desc="Product Image" clickable="true"/></node><node><node class='
           '"android.widget.TextView" text="Lamp"/><node class="android.widget.ImageView" resource-id="product" '
           'content-desc="Product Image" clickable="true"/></node></hierarchy>')
    assert len(safe_navigation_elements(extract_screen(xml, "com.example", "test"))) == 1
    single = xml.split("<node><node class=\"android.widget.TextView\" text=\"Lamp\"")[0] + "</hierarchy>"
    assert safe_navigation_elements(extract_screen(single, "com.example", "test")) == []  # a detail screen's picture


def test_drawer_items_are_explored_first_and_a_dialog_is_closed_without_a_relaunch(run):
    labels = [a["label"] for a in run["result"]["actions"]]
    first_menu = labels.index("View menu")
    assert {"Catalog", "About", "Drawing", "Log In"} <= set(labels)
    discovery = json.loads((run["dir"] / "android_discovery.json").read_text(encoding="utf-8"))
    exploring = discovery["navigation_action_count"] - run["result"]["interaction"].get("tries_used", 0) * 0
    assert discovery["discovery_recovery_action_count"] <= 2 * max(1, exploring)
    assert first_menu < labels.index("Product Image")


def test_a_screen_cap_lists_the_rest_as_not_reached(tmp_path):
    result = explore(tmp_path, FakeDemoApp(), max_candidates_per_screen=1, interaction_testing=False)
    capped = [u for u in result["unvisited"] if "candidate cap reached" in u["reason"]]
    assert capped and all(u["screen_id"] for u in capped)


def test_an_uploaded_apk_keeps_the_package_it_turned_out_to_be(tmp_path):
    (tmp_path / ".private").mkdir()
    (tmp_path / ".private" / "android_config.json").write_text(json.dumps({"app_mode": "apk", "package_name": ""}))
    explore(tmp_path, FakeDemoApp(), app_mode="apk", interaction_testing=False, max_actions=0)
    assert json.loads((tmp_path / ".private" / "android_config.json").read_text())["package_name"] == PACKAGE


# ------------------------------------------------------------------ 2. scrolling keeps the screen's identity

def test_a_scrolled_screen_is_still_the_same_screen():
    def page(first):
        rows = "".join(f'<node class="android.widget.TextView" resource-id="{PACKAGE}:id/row" text="Row {i}" '
                       f'bounds="[0,{(i - first) * 100 + 200}][1080,{(i - first) * 100 + 290}]"/>' for i in range(first, first + 8))
        return (f'<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1080,2000]">'
                f'<node class="android.widget.TextView" resource-id="{PACKAGE}:id/toolbarTitle" text="Products" '
                f'bounds="[0,0][1080,150]"/><node class="android.widget.ScrollView" scrollable="true" '
                f'resource-id="{PACKAGE}:id/list" bounds="[0,150][1080,2000]">{rows}</node></node></hierarchy>')
    top, scrolled = (extract_screen(page(n), PACKAGE, "emulator-5554", ".Main") for n in (1, 6))
    assert top["fingerprint"] != scrolled["fingerprint"] and top["identity"] == scrolled["identity"]
    assert same_screen(top, scrolled)
    no_toolbar = page(1).replace('text="Products"', 'text=""')
    a, b = (extract_screen(x, PACKAGE, "emulator-5554", ".Main") for x in (no_toolbar, page(6).replace('text="Products"', 'text=""')))
    assert a["identity"] == b["identity"] and a["identity"][2] == "scroller"


# ------------------------------------------------------------------ 3. what is in front of the app

def test_the_keyboard_is_not_another_app():
    app = FakeDemoApp(keyboard_ime=True)
    app.keyboard = True
    assert app.current_package == IME
    screen = inspect_driver(app, {**CONFIG})
    assert screen["package_name"] == PACKAGE and not app.keyboard


def test_a_permission_prompt_is_declined_in_test_mode_and_named_otherwise():
    app = FakeDemoApp()
    app.prompt = "take pictures and record video"
    with pytest.raises(Exception, match=PERMISSIONS):
        inspect_driver(app, {**CONFIG, "interaction_testing": False})
    assert app.prompt and app.pressed == []  # outside test mode nothing is pressed
    assert inspect_driver(app, CONFIG)["package_name"] == PACKAGE
    assert app.declined == ["take pictures and record video"] and "While using the app" not in app.pressed
    assert app._blowai_declined == ["Allow My Demo App to take pictures and record video?"]


def test_another_app_in_front_is_named_by_its_package_only(monkeypatch):
    app = FakeDemoApp()
    monkeypatch.setattr(FakeDemoApp, "current_package", property(lambda self: "com.android.chrome"))
    with pytest.raises(Exception, match=r"com\.android\.chrome came to the front"):
        inspect_driver(app, CONFIG)


# ------------------------------------------------------------------ 4. no false "the login was accepted"

def test_a_password_box_hidden_by_the_keyboard_is_not_a_login_that_was_accepted(tmp_path):
    result = explore(tmp_path, FakeDemoApp(cover_password=True))
    findings = result["interaction"]["findings"]
    assert not any("accepted" in f["finding"] for f in findings)
    assert any(t.startswith("Login with a wrong password is refused") for t in
               [i["flow"]["title"] for i in result["auto_flows"]])


def test_a_wrong_password_that_really_logs_in_is_a_finding_with_its_evidence(tmp_path):
    result = explore(tmp_path, FakeDemoApp(accept_wrong=True))
    finding = next(f for f in result["interaction"]["findings"] if f["finding"] == "Login with a wrong password was accepted")
    assert "opened" in finding["detail"] or "appeared" in finding["detail"]
    kept = next(i for i in result["auto_flows"] if i["flow"]["title"] == "Login with a wrong password is refused")
    assert kept["meta"]["discovery_replay"].startswith("failed twice")
    row = next(t for t in result["interaction"]["tried"] if t["check"] == "Login with a wrong password is refused")
    assert row["outcome"] == "kept" and row["reason"].startswith("finding")


# ------------------------------------------------------------------ 5. every feature, except checkout

def test_the_menu_is_opened_first_and_every_item_opens_its_screen(run):
    titles = run["titles"]
    assert titles[0] == "Open the app menu 'View menu': 8 items appear"
    for item, heading in (("Catalog", "Products"), ("About", "About"), ("Drawing", "Drawing"),
                          ("QR Code Scanner", "QR Code Scanner"), ("Geo Location", "Geo Location"),
                          ("FingerPrint", "FingerPrint"), ("Log In", "Login")):
        assert f"Menu item '{item}': '{heading}' opens" in titles, item


def test_device_feature_screens_open_but_their_feature_is_never_used(run):
    pressed = run["app"].pressed
    assert not any(p in pressed for p in ("Scan a QR code", "Show my location", "Use fingerprint to login"))
    assert "While using the app" not in pressed and "Don’t allow" in pressed
    for control in ("'Scan a QR code'", "'Show my location'", "'Use fingerprint to login'"):
        row = next(r for r in run["rows"] if r["name"] == control)
        assert row["status"] == "not tested" and "device features" in row["reason"]
    declined = [r for r in run["rows"] if r["name"].endswith("Android permission prompt")]
    assert len(declined) == 2 and all("was declined" in r["reason"] for r in declined)
    qr = flow(run, "Menu item 'QR Code Scanner'")
    assert any(s.get("purpose") == "navigation" for s in qr["steps"])  # opens the screen, nothing more
    for label in ("Virtual USB", "FingerPrint", "QR Code Scanner", "Geo Location"):
        assert never_in_test_mode(label, native=True) and not never_in_test_mode(label, native=False)


def test_never_pressed_controls_say_exactly_why(run):
    reasons = {r["name"]: r["reason"] for r in run["rows"] if r["status"] == "not tested"}
    assert reasons["'Proceed To Checkout'"] == "checkout, payment and placing an order are never tested"
    assert reasons["'Reset App State'"].startswith("not pressed: it resets the app's data")
    assert "Proceed To Checkout" not in run["app"].pressed and "Reset App State" not in run["app"].pressed
    tried = next(t for t in run["tried"] if t["check"].startswith("Tap 'Reset App State'"))
    assert tried["reason"].startswith("not pressed")


def test_products_quantity_and_the_cart_are_used_like_a_user(run):
    titles = run["titles"]
    assert "Open the first 'Product Image' on Products: 'Sauce Labs Backpack' opens" in titles
    assert "Tap 'Increase item quantity' on Sauce Labs Backpack: 'noTV' changes from '1' to '2'" in titles
    assert "Tap 'Decrease item quantity' at the lowest count on Sauce Labs Backpack: the count stays '1'" in titles
    assert "Add 'Sauce Labs Backpack' to the cart twice: 'cartTV' changes from '1' to '2'" in titles
    assert "Tap 'Add To Cart' on Sauce Labs Backpack: '1' appears" in titles
    assert "The cart lists 'Sauce Labs Backpack' after Add To Cart" in titles
    assert any(t.startswith("Tap 'Remove Item'") and "'No Items' appears" in t for t in titles)
    assert any(t.startswith("Tap 'Go Shopping' on No Items") for t in titles)
    assert sum(t.startswith("Tap 'start") for t in titles) == 1  # one rating star stands for all


def test_every_sort_option_is_tried_and_must_change_the_order(run):
    titles = run["titles"]
    assert "Sort by 'Name - Descending' on Products: 'titleTV' changes from 'Sauce Labs Backpack' to " \
           "'Sauce Labs Onesie', 'priceTV' changes from '$ 29.99' to '$ 7.99'" in titles
    unchanged = next(r for r in run["rows"] if r["name"] == "Sort by 'Name - Ascending' on Products")
    assert unchanged["status"] == "not tested" and "did not change" in unchanged["reason"]
    sort = flow(run, "Sort by 'Name - Descending'")
    assert sort["steps"][-2]["locator"]["value"].startswith("(//*[@resource-id=")  # the FIRST title, by place


def test_login_like_a_user_then_log_out(run):
    titles = run["titles"]
    for title in ("Login with empty fields is refused: 'Username is required' appears",
                  "Login with the locked-out sample user is refused: 'Sorry this user has been locked out.' appears",
                  "Login with the app's sample user succeeds",
                  "Log out from the app menu: 'You are successfully logged out.' appears, 'OK' appears"):
        assert title in titles, title
    assert any(t.startswith("Login with a wrong password is refused") for t in titles)


def test_kept_flows_become_readable_tests_and_every_control_is_listed(run):
    from backend.android_features import feature_matrix
    from backend.android_reporting import control_coverage, early_stop, render_mobile_report
    state = {**run["result"], "run_dir": str(run["dir"]), "run_id": "r",
             "config": {**run["result"]["config"], "verify_observed_navigation": True, "max_test_cases": 300}}
    designed = android_pipeline.test_design_agent(state)
    cases = designed["test_cases"]
    assert not any(c["title"].startswith("Replay observed navigation") for c in cases)
    assert any(c["title"].startswith("Tap 'View menu' on Products: ") and c["title"].endswith("' opens") for c in cases)
    assert android_pipeline.script_generator_agent({**state, **designed})["scripts"]
    results = [{"id": c["id"], "outcome": "passed", "checks": 1, "auto_flow_id": c.get("auto_flow_id")}
               for c in cases if not c.get("blocked")]
    features = feature_matrix({**state, **designed, "results": results})
    assert isinstance(features["controls_needing_functional_checks"], list)
    controls = control_coverage(state, features, cases, results)
    rows = controls["rows"]
    assert rows and all(r["status"] in ("passed", "failed", "not tested") and r["reason"] for r in rows)
    assert sum(controls["counts"].values()) == len(rows)
    assert early_stop(state) == ""
    summary = {"counts": {"passed": len(results), "failed": 0, "error": 0}, "verdict": "Ready", "screens_visited": 3,
               "self_healing_attempts": 0, "reasons": [], "gates": [], "coverage": {"tested": 1, "unvisited": []},
               "package_name": PACKAGE, "android_version": "16", "device_id": "emulator-5554", "run_id": "r",
               "interaction": state["interaction"], "user_like_tests": {"total": 1, "passed": 1, "failed": 0},
               "app_crashes": 0, "controls": controls, "early_stop": "User-like testing stopped early (time); 4 planned "
                                                                     "checks were not reached."}
    page = render_mobile_report(summary, [], [], [], run["result"]["screens"], [])
    assert "Every control" in page and page.index("Stopped early") < page.index("Quality gates")


def test_a_run_that_runs_out_of_time_says_so_with_what_was_not_reached(tmp_path):
    from backend.android_reporting import early_stop
    result = explore(tmp_path, FakeDemoApp(), max_interactions=6)
    assert result["interaction"]["stopped"] == "User-like test limit reached"
    assert "planned checks were not reached" in early_stop(result)


# ------------------------------------------------------------------ 6. live run android_20261110_110821_90cd6d

def test_screens_that_share_a_scroll_view_description_are_told_apart(run):
    """Login and Products both carry "Scrollview manages views in given screen size": Login was taken for Products,
    never recorded, and its login form never tested."""
    app = FakeDemoApp()
    products = extract_screen(app.page_source, PACKAGE, "emulator-5554", app.current_activity)
    app.screen = "login"
    login = extract_screen(app.page_source, PACKAGE, "emulator-5554", app.current_activity)
    assert products["identity"][:2] == login["identity"][:2] == ["container", "Scrollview manages views in given screen size"]
    assert products["identity"] != login["identity"] and not same_screen(products, login)
    assert "Login" in [s["screen_name"] for s in run["result"]["screens"]]


def test_a_screen_first_reached_in_test_mode_is_recorded_and_its_forms_tested(tmp_path):
    """Discovery stopped before 'Log In'; test mode opened it from the menu but only tested discovery's screens."""
    result = explore(tmp_path, FakeDemoApp(), max_actions=3)
    assert "Log In" not in [a["label"] for a in result["actions"]]
    login = next(s for s in result["screens"] if s["screen_name"] == "Login")
    assert len(login["path"]) == 2 and "screenshot" in login  # menu button, then 'Log In' (no picture: input boxes)
    titles = [i["flow"]["title"] for i in result["auto_flows"]]
    for start in ("Login with empty fields is refused", "Login with a wrong password is refused",
                  "Login with the locked-out sample user is refused", "Login with the app's sample user succeeds",
                  "Log out from the app menu"):
        assert any(t.startswith(start) for t in titles), start


def test_returning_takes_one_tap_and_is_not_counted_as_recovery(run):
    discovery = json.loads((run["dir"] / "android_discovery.json").read_text(encoding="utf-8"))
    assert discovery["cheap_return_action_count"] > 0
    assert discovery["discovery_recovery_action_count"] <= discovery["navigation_action_count"]
    assert not any(i.get("recovery_heavy") for i in run["result"]["discovery_issues"])


def test_a_screen_with_its_expected_identity_is_settled_at_once():
    from backend.android_runtime import settled_screen
    frames = iter([{"identity": ["activity", ".Main", "heading", "products"], "fingerprint": str(n), "loading": False,
                    "package_name": PACKAGE, "activity": ".Main",
                    "elements": [{"visible": True, "locators": [1], "text": "Products"}]} for n in range(5)])
    expected = {"identity": ["activity", ".Main", "heading", "products"], "fingerprint": "old", "package_name": PACKAGE,
                "activity": ".Main", "elements": []}
    with VirtualClock():
        screen = settled_screen(lambda: next(frames), expected, timeout=5)
    assert screen["fingerprint"] == "0"  # the first frame: no second identical frame needed


def test_the_final_run_declines_a_prompt_left_in_front_and_records_it(tmp_path):
    """navigation_007 raised a permission prompt; 008-010 then failed 'did not enter the foreground'."""
    from backend.android_runtime import MobileRuntime
    app = FakeDemoApp(prompt_delay=3)  # the prompt is still opening when it is first looked at
    launch = extract_screen(app.page_source, PACKAGE, "emulator-5554", app.current_activity)
    from backend.android_design import normalize_screens
    screens = normalize_screens([launch])
    app.prompt = "take pictures and record video"
    runtime = MobileRuntime(app, {**CONFIG}, screens, {}, tmp_path)
    with VirtualClock():
        runtime.wait_for_start()
    assert app.current_package == PACKAGE and app.declined == ["take pictures and record video"]
    assert any(step["text"].startswith("Declined the Android permission prompt") for step in runtime.steps)
    app.prompt = "access this device’s location"
    outside = MobileRuntime(app, {**CONFIG, "interaction_testing": False}, screens, {}, tmp_path)
    with VirtualClock(), pytest.raises(Exception, match="did not enter the foreground"):
        outside.wait_for_start()  # outside test mode nothing is pressed
    template = (Path(android_pipeline.__file__).parent / "templates" / "android_conftest.py").read_text(encoding="utf-8")
    assert template.count("bring_app_back(driver") == 2  # before each test and when it ends


def test_a_quantity_that_drops_below_one_is_a_finding_not_a_pass(tmp_path):
    """'Tap Decrease at the lowest count: noTV changes from 1 to 0' was kept as a passing test."""
    result = explore(tmp_path, FakeDemoApp(allow_zero=True))
    assert any(f["finding"] == "'-' lets the quantity drop from 1 to 0" for f in result["interaction"]["findings"])
    kept = next(i for i in result["auto_flows"] if "at the lowest count" in i["flow"]["title"])
    assert kept["flow"]["title"].endswith("the count stays '1'") and kept["meta"]["discovery_replay"].startswith("failed twice")


def test_an_api_key_names_its_provider_and_the_ui_sends_the_test_mode_limits():
    from backend.server import key_provider
    assert key_provider("sk-ant-api03-x") == "anthropic" and key_provider("sk-proj-x") == "openai"
    assert key_provider("AIzaSy-x") == "gemini" and key_provider("ollama-local") is None
    root = Path(android_pipeline.__file__).resolve().parent.parent / "frontend"
    page, script = (root / "chat.html").read_text(encoding="utf-8"), (root / "chat.js").read_text(encoding="utf-8")
    assert 'id="androidMaxInteractions" type="number" min="0" max="500" value="300"' in page
    assert 'id="androidInteractionTimeout" type="number" min="30" max="3600" value="2700"' in page
    assert 'data.append("max_interactions"' in script and 'data.append("interaction_timeout_s"' in script
