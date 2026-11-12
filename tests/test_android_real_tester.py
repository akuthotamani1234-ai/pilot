"""Real-tester behaviour for Android: search-link unwrapping, recovery after leaving the app, test-build mode
(undoable actions, login/form checks, phone checks, replay verification), crash/ANR evidence and reporting."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import android, android_interact, android_pipeline
from backend.android import AndroidEnvironmentError, extract_screen, interaction_blocker, validate_mobile_config
from backend.android_design import normalize_screens
from backend.qa_contracts import parse_contract

PACKAGE = "com.example.shop"
BING = ("https://www.bing.com/ck/a?!&&p=7d73a44f14b1432b08cba3d96fb8e80032fc10b3fde6edb1ed4c6c1557cdfb36JmltdHM9MTc5NDE4"
        "MjQwMA&ptn=3&ver=2&hsh=4&fclid=2dba9422-422b-639f-00cb-83ce462b6d20&psq=saucedomo+website+login"
        "&u=a1aHR0cHM6Ly9zYXVjZS1kZW1vLm15c2hvcGlmeS5jb20v")


# ------------------------------------------------------------------ 1. search-engine links

@pytest.mark.parametrize("link, real", [
    (BING, "https://sauce-demo.myshopify.com/"),
    ("https://www.google.com/url?q=https://www.saucedemo.com/&sa=U", "https://www.saucedemo.com/"),
    ("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2F", "https://example.com/"),
    ("https://r.search.yahoo.com/_ylt=x/RV=2/RU=https%3a%2f%2fexample.org%2f/RK=2/RS=x-", "https://example.org/"),
    ("https://www.saucedemo.com/", "https://www.saucedemo.com/"),
])
def test_android_chrome_tests_the_real_site_behind_a_search_link(link, real):
    config = validate_mobile_config({"app_mode": "web", "device_id": "emulator-5554", "start_url": link})
    assert config["start_url"] == real


def test_an_undecodable_search_link_is_rejected_before_appium_starts():
    with pytest.raises(AndroidEnvironmentError, match="search-engine link"):
        validate_mobile_config({"app_mode": "web", "device_id": "emulator-5554",
                                "start_url": "https://www.bing.com/ck/a?!&&p=abc"})


def test_unwrap_link_is_still_importable_from_discovery():
    from backend.agents.discovery import unwrap_link
    assert unwrap_link(BING) == "https://sauce-demo.myshopify.com/"


# ------------------------------------------------------------------ 2. leaving the app does not end discovery

START = """<hierarchy>
<node class="android.widget.Button" resource-id="com.example:id/help" content-desc="Open help" text="Open help" clickable="true" bounds="[0,0][100,50]"/>
<node class="android.widget.Button" resource-id="com.example:id/about" text="About" clickable="true" bounds="[0,50][100,100]"/>
</hierarchy>"""
ABOUT = """<hierarchy><node class="android.widget.TextView" resource-id="com.example:id/about_title" text="About us" bounds="[0,0][100,50]"/></hierarchy>"""


class LeavingDriver:
    """'Open help' opens another app (the browser); activate_app returns before the app is back in front (a real race).
    It is a Help control: "image" is not safe navigation, so the earlier 'Open image' was never explored at all."""
    current_activity = ".Main"

    def __init__(self):
        self.page_source, self.package, self.pending = START, "com.example", 0
        self.activations = 0

    @property
    def current_package(self):
        if self.pending:
            self.pending -= 1
            return "com.android.chrome"
        return self.package

    def find_elements(self, _by, value):
        driver = self

        class Element:
            def is_displayed(self):
                return True

            def is_enabled(self):
                return True

            def click(self):
                if "help" in value.lower():
                    driver.package = "com.android.chrome"
                else:
                    driver.page_source = ABOUT

        return [Element()]

    def activate_app(self, _package):
        self.activations += 1
        self.package, self.page_source, self.pending = "com.example", START, 2

    def terminate_app(self, _package):
        self.page_source = START

    def back(self):
        self.page_source = START

    def quit(self):
        pass


def test_a_control_that_opens_another_app_is_recorded_and_discovery_continues(tmp_path, monkeypatch):
    driver = LeavingDriver()
    monkeypatch.setattr(android_pipeline, "create_session", lambda _config: driver)
    state = {"config": {"app_mode": "installed", "package_name": "com.example", "device_id": "emulator-5554",
                        "appium_url": "http://127.0.0.1:4723", "max_actions": 5, "max_screens": 5},
             "run_dir": str(tmp_path), "log": []}

    result = android_pipeline.discovery_agent(state)

    outcomes = {a["label"]: a["outcome"] for a in result["actions"]}
    assert outcomes == {"Open help": "left_app", "About": "observed"}  # About was still explored
    assert [s["screen_name"] for s in result["screens"]] == [".Main", "About us"]
    assert not any("remaining controls were not touched" in i.get("error", "") for i in result["discovery_issues"])
    assert driver.activations >= 1


# ------------------------------------------------------------------ 3. phone actions in flows

def _contract(steps):
    return parse_contract({"version": 1, "test_environment": True,
                           "flows": [{"id": "f", "title": "t", "approved": True, "steps": steps}]})


def test_phone_actions_are_valid_flow_steps():
    contract = _contract([{"action": "rotate", "value": "landscape"}, {"action": "background", "value": "3"},
                          {"action": "back"}, {"action": "hide_keyboard"},
                          {"action": "long_press", "locator": {"strategy": "accessibility_id", "value": "Item"}},
                          {"action": "assert_visible", "locator": {"strategy": "accessibility_id", "value": "Item"}}])
    assert [s.action for s in contract.flows[0].steps][:5] == ["rotate", "background", "back", "hide_keyboard", "long_press"]


@pytest.mark.parametrize("step", [
    {"action": "rotate", "value": "sideways"},
    {"action": "background", "value": "0"},
    {"action": "background", "value": "99"},
    {"action": "background"},
    {"action": "back", "value": "x"},
    {"action": "back", "locator": {"strategy": "text", "value": "Home"}},
    {"action": "long_press"},
    {"action": "long_press", "locator": {"strategy": "accessibility_id", "value": "Delete item"}},
])
def test_invalid_or_irreversible_phone_steps_are_rejected(step):
    with pytest.raises(ValueError):
        _contract([step, {"action": "assert_visible", "locator": {"strategy": "text", "value": "x"}}])


# ------------------------------------------------------------------ 4. a fake app, driven like a real one

class FakeElement:
    def __init__(self, app, node):
        self.app, self.node = app, node
        self.id = "el-" + node["key"]

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def click(self):
        self.app.click(self.node["key"])

    def clear(self):
        self.app.fields[self.node["key"]] = ""

    def send_keys(self, value):
        self.app.fields[self.node["key"]] = value

    @property
    def text(self):
        if self.node.get("input"):
            return self.app.fields.get(self.node["key"], "") or self.node.get("hint", "")
        return self.node.get("text", "")

    @property
    def rect(self):
        return {"x": 0, "y": 0, "width": 100, "height": 100}

    def get_attribute(self, name):
        if name == "password":
            return "true" if self.node.get("password") else "false"
        if name == "class":
            return "android.widget.EditText" if self.node.get("input") else "android.widget.Button"
        if name == "showing-hint":
            return "true" if self.node.get("input") and not self.app.fields.get(self.node["key"]) else "false"
        if name == "resource-id":
            return "id/" + self.node["key"]
        if name == "content-desc":
            return self.node.get("desc", "")
        return None


class FakeApp:
    """A shop: Add To Cart shows a cart badge. A login screen: refuses empty and wrong input (or accepts it)."""

    def __init__(self, kind="shop", accept_wrong=False, crash_on_add=False):
        self.kind, self.accept_wrong, self.crash_on_add = kind, accept_wrong, crash_on_add
        self.orientation_changes = 0
        self.reset()

    def reset(self):
        self.cart, self.error, self.logged_in, self.fields = 0, "", False, {}

    def nodes(self):
        if self.kind == "shop":
            nodes = [{"key": "title", "text": "Products", "cls": "TextView"},
                     {"key": "add", "desc": "Add To Cart", "text": "Add To Cart", "click": True},
                     {"key": "checkout", "desc": "Checkout", "text": "Checkout", "click": True}]
            if self.cart:
                nodes.append({"key": "cart_badge", "text": str(self.cart), "cls": "TextView"})
            return nodes
        if self.logged_in:
            return [{"key": "welcome", "text": "Welcome", "cls": "TextView"}]
        nodes = [{"key": "heading", "text": "Sign in to the shop", "cls": "TextView"},
                 {"key": "username", "input": True, "hint": "Username"},
                 {"key": "password", "input": True, "password": True, "hint": "Password"},
                 {"key": "login", "desc": "Login button", "text": "Login", "click": True}]
        if self.error:
            nodes.append({"key": "", "text": self.error, "cls": "TextView"})
        return nodes

    def xml(self):
        parts = []
        for index, node in enumerate(self.nodes()):
            cls = "android.widget.EditText" if node.get("input") else "android.widget." + node.get("cls", "Button")
            attrs = {"class": cls, "bounds": f"[0,{index * 60}][300,{index * 60 + 50}]",
                     "resource-id": f"{PACKAGE}:id/{node['key']}" if node["key"] else "",
                     "content-desc": node.get("desc", ""), "clickable": "true" if node.get("click") or node.get("input") else "false",
                     "text": self.fields.get(node["key"], "") or node.get("hint", "") if node.get("input") else node.get("text", ""),
                     "password": "true" if node.get("password") else "false", "hint": node.get("hint", "")}
            parts.append("<node " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + "/>")
        return "<hierarchy>" + "".join(parts) + "</hierarchy>"

    def click(self, key):
        if key == "add":
            if self.crash_on_add:
                raise RuntimeError("app crashed")
            self.cart += 1
        elif key == "login":
            user, password = self.fields.get("username", ""), self.fields.get("password", "")
            if not user or not password:
                self.error = "Username and password are required"
            elif password == "right-password" or self.accept_wrong:
                self.logged_in, self.error = True, ""
            else:
                self.error = "Wrong username or password"

    def find(self, using, value):
        for node in self.nodes():
            if (using == "accessibility id" and node.get("desc") == value
                    or using == "id" and node["key"] and value == f"{PACKAGE}:id/{node['key']}"
                    or using == "-android uiautomator" and json.dumps(node.get("text", "")) in value and node.get("text")):
                return [FakeElement(self, node)]
        return []


class FakeDriver:
    current_context = "NATIVE_APP"
    current_activity = ".Main"
    capabilities = {}

    def __init__(self, app):
        self.app = app
        self.current_package = PACKAGE
        self.switch_to = SimpleNamespace(context=lambda _c: None)

    @property
    def page_source(self):
        return self.app.xml()

    def find_elements(self, using, value):
        return self.app.find(using, value)

    def is_keyboard_shown(self):
        return False

    def back(self):
        pass

    @property
    def orientation(self):
        return "PORTRAIT"

    @orientation.setter
    def orientation(self, _value):
        self.app.orientation_changes += 1

    def background_app(self, _seconds):
        pass

    def execute_script(self, name, _args=None):
        if name == "mobile: clearApp":
            self.app.reset()
        return []


def _session(app, tmp_path, environment=None, max_tries=60):
    driver = FakeDriver(app)
    config = {"app_mode": "apk", "device_id": "emulator-5554", "package_name": PACKAGE, "interaction_testing": True}
    launch = extract_screen(app.xml(), PACKAGE, "emulator-5554", ".Main")
    launch["screen_name"] = "Products" if app.kind == "shop" else "Sign in"
    screens = normalize_screens([launch])

    def fresh_start():
        app.reset()
        return extract_screen(app.xml(), PACKAGE, "emulator-5554", ".Main")

    device = SimpleNamespace(driver=driver, config=config, screens=screens, stop_path=tmp_path / "STOP",
                             deadline=time.monotonic() + 900, max_tries=max_tries, fresh_start=fresh_start,
                             go_to=lambda _screen: fresh_start(),
                             observe=lambda: extract_screen(app.xml(), PACKAGE, "emulator-5554", ".Main"))
    return android_interact.Session(device, environment=environment or {}), screens


@pytest.fixture(autouse=True)
def _virtual_clock(monkeypatch):
    """Waiting advances a virtual clock: bounded waits end at once, without sleeping or busy-looping."""
    offset, real = [0.0], time.monotonic
    monkeypatch.setattr(time, "sleep", lambda seconds: offset.__setitem__(0, offset[0] + seconds))
    monkeypatch.setattr(time, "monotonic", lambda: real() + offset[0])


def test_an_undoable_action_becomes_a_replay_verified_test(tmp_path):
    session, screens = _session(FakeApp("shop"), tmp_path)

    session.run()

    kept = [item for item in session.flows if item["meta"]["category"] == "user_action"]
    assert len(kept) == 1
    flow = kept[0]["flow"]
    assert flow["title"] == "Tap 'Add To Cart' on Products: 'cart_badge' changes to '1'" or "'1' appears" in flow["title"]
    assert flow["steps"][-1] == {**flow["steps"][-1], "action": "assert_text", "value": "1"}
    assert kept[0]["meta"]["discovery_replay"] == "passed"
    # Checkout is never touched, by discovery or by user-like testing: it is only listed as never tested, with why
    assert all(item["outcome"] == "intentionally excluded" for item in session.tried if "Checkout" in item["check"])
    assert any(row["name"] == "'Checkout'" and row["status"] == "not tested" and "checkout" in row["reason"]
               for row in session.coverage)
    assert not any((step.get("locator") or {}).get("value") == "Checkout"
                   for item in session.flows for step in item["flow"]["steps"])


def test_behaviour_that_does_not_repeat_is_dropped_not_kept_as_a_flaky_test(tmp_path):
    session, _ = _session(FakeApp("shop"), tmp_path)
    # The replay sees a different app state than the observation did (for example a counter kept on a server).
    session.replay = lambda _flow: "AssertionError: Expected text '1', found '6'."

    session.run()

    assert not [i for i in session.flows if i["meta"]["category"] == "user_action"]
    assert any(t["outcome"] == "not repeatable" for t in session.tried)


def test_login_checks_refuse_empty_and_wrong_input_with_the_observed_message(tmp_path):
    session, _ = _session(FakeApp("login"), tmp_path)

    session.run()

    titles = [item["flow"]["title"] for item in session.flows]
    assert any(t.startswith("Login with empty fields is refused") and "required" in t for t in titles)
    assert any(t.startswith("Login with a wrong password is refused") for t in titles)
    assert not any("test account" in t for t in titles)  # no account was given
    wrong = next(item["flow"] for item in session.flows if item["flow"]["title"].startswith("Login with a wrong"))
    password_step = next(s for s in wrong["steps"] if s["action"] == "fill" and s.get("sensitive"))
    assert password_step["secret_ref"] == android_interact.WRONG_PASSWORD and password_step.get("value") is None
    assert not session.findings


def test_the_real_test_account_is_used_only_through_secret_references(tmp_path):
    environment = {"BLOWAI_SECRET_TEST_USERNAME": "qa-user", "BLOWAI_SECRET_TEST_PASSWORD": "right-password"}
    session, _ = _session(FakeApp("login"), tmp_path, environment=environment)

    session.run()

    login = next(item for item in session.flows if item["meta"]["category"] == "login")
    assert login["flow"]["authentication"] is True
    assert login["meta"]["discovery_replay"] == "passed"
    assert "right-password" not in json.dumps(session.contract()) and "qa-user" not in json.dumps(session.contract())


def test_an_app_that_accepts_a_wrong_password_gets_a_finding_and_a_failing_test(tmp_path):
    session, _ = _session(FakeApp("login", accept_wrong=True), tmp_path)

    session.run()

    assert any(f["finding"] == "Login with a wrong password was accepted" for f in session.findings)
    wrong = next(item for item in session.flows if item["flow"]["title"] == "Login with a wrong password is refused")
    assert wrong["meta"]["universal"] and wrong["meta"]["discovery_replay"].startswith("failed twice")


def test_phone_checks_rotate_and_resume_the_launch_screen(tmp_path):
    app = FakeApp("shop")
    session, _ = _session(app, tmp_path)

    session.run()

    device = [item["flow"]["title"] for item in session.flows if item["meta"]["category"] == "device"]
    assert "Products survives rotating the phone" in device
    assert "Products comes back after leaving the app" in device
    assert app.orientation_changes >= 2


def test_the_budget_stops_cleanly_and_one_broken_check_never_stops_the_others(tmp_path):
    session, _ = _session(FakeApp("shop", crash_on_add=True), tmp_path, max_tries=4)

    stopped = session.run()

    assert any(t["outcome"] == "could not be tried" for t in session.tried)
    assert stopped == "User-like test limit reached" or session.used <= 4


def test_test_mode_is_refused_where_it_could_reset_a_real_phone_or_was_not_confirmed():
    assert interaction_blocker({"interaction_testing": False}) == "Test-build mode is off."
    # A website in Chrome: the ticked box is the person's confirmation that it is a test / demo site they may test
    assert interaction_blocker({"interaction_testing": True, "app_mode": "web"}) == ""
    assert interaction_blocker({"interaction_testing": False, "app_mode": "web"}) == "Test-build mode is off."
    assert "physical phone" in interaction_blocker({"interaction_testing": True, "app_mode": "installed", "device_id": "R58M"})
    assert interaction_blocker({"interaction_testing": True, "app_mode": "installed", "device_id": "emulator-5554"}) == ""
    assert interaction_blocker({"interaction_testing": True, "app_mode": "apk", "device_id": "R58M"}) == ""


# ------------------------------------------------------------------ 5. design, scripts and the runtime

def test_kept_flows_become_cases_that_run_last_and_validate_as_scripts(tmp_path):
    session, screens = _session(FakeApp("shop"), tmp_path)
    session.run()
    state = {"config": {"app_mode": "apk", "device_id": "emulator-5554", "max_test_cases": 100,
                        "expected_destinations": {}, "expected_values": {}},
             "run_dir": str(tmp_path), "screens": screens, "actions": [], "auto_flows": session.flows, "log": []}

    designed = android_pipeline.test_design_agent(state)

    cases = designed["test_cases"]
    kinds = [c["kind"] for c in cases if not c.get("blocked")]
    first = kinds.index("interaction")
    assert first > 0 and all(k == "interaction" for k in kinds[first:])  # read-only checks first, data changes last
    flow_case = next(c for c in cases if c.get("auto_flow_id"))
    assert flow_case["plan"] == [["assert_flow", [flow_case["auto_flow_id"]]]] and flow_case["reset_app_data"]
    blocked = next((c for c in cases if c.get("blocked")), None)
    add = next(e for e in screens[0]["elements"] if e.get("accessibility_id") == "Add To Cart")
    assert blocked is None or add["id"] not in blocked["element_ids"]  # exercised controls are not "unexercised"
    (tmp_path / ".private").mkdir(exist_ok=True)
    scripts = android_pipeline.script_generator_agent({**state, "test_cases": cases})
    assert scripts["scripts"] and "mobile.assert_flow(" in Path(scripts["scripts"][0]).read_text(encoding="utf-8")


def test_assert_flow_runs_a_kept_flow_through_the_trusted_runtime(tmp_path, monkeypatch):
    from backend.android_runtime import MobileRuntime

    app = FakeApp("shop")
    session, screens = _session(app, tmp_path)
    session.run()
    (tmp_path / ".private").mkdir(exist_ok=True)
    (tmp_path / ".private" / "auto_contract.json").write_text(json.dumps(session.contract()), encoding="utf-8")
    monkeypatch.setenv("ANDROID_CONTRACT_INPUTS", json.dumps({"secrets": android_interact.generated_secrets(), "databases": {}}))
    flow_id = next(i["flow"]["id"] for i in session.flows if i["meta"]["category"] == "user_action")
    app.reset()
    runtime = MobileRuntime(FakeDriver(app), {"app_mode": "apk", "device_id": "emulator-5554"}, screens, {}, tmp_path)

    runtime.assert_flow(flow_id)

    assert runtime.checks >= 1 and app.cart == 1
    with pytest.raises(ValueError, match="Unknown"):
        runtime.assert_flow("auto_invented_999")


def test_a_failed_rotation_flow_still_restores_portrait(tmp_path):
    from backend.qa_runtime import AndroidContractAdapter, ContractRuntime

    app = FakeApp("shop")
    driver = FakeDriver(app)
    contract = parse_contract({"version": 1, "test_environment": True, "flows": [{"id": "r", "title": "r", "approved": True, "steps": [
        {"action": "rotate", "value": "landscape"},
        {"action": "assert_text", "locator": {"strategy": "accessibility_id", "value": "Add To Cart"}, "value": "Wrong"}]}]})
    runtime = ContractRuntime(AndroidContractAdapter(driver, {"package_name": PACKAGE, "app_mode": "apk"}, contract),
                              contract.model_dump(), {"secrets": {}, "databases": {}})
    with pytest.raises(AssertionError):
        runtime.execute("r")
    assert app.orientation_changes == 2  # landscape, then back to portrait despite the failure


# ------------------------------------------------------------------ 6. crash / ANR evidence

CRASH_LOG = """1731167200.100  4321  4321 E AndroidRuntime: FATAL EXCEPTION: main
1731167200.101  4321  4321 E AndroidRuntime: Process: com.example.shop, PID: 4321
1731167200.102  4321  4321 E AndroidRuntime: java.lang.IllegalStateException: Cart is null
1731167200.103  4321  4321 E AndroidRuntime: 	at com.example.shop.Cart.add(Cart.java:42)
1731167200.200  1000  1000 I OtherApp: unrelated
""".splitlines()


def test_a_crash_of_this_app_is_found_with_its_exception():
    from backend.android_evidence import app_problem
    assert app_problem(CRASH_LOG, PACKAGE) == {"kind": "crash", "summary": "java.lang.IllegalStateException: Cart is null"}
    assert app_problem(CRASH_LOG, "com.other.app") is None


def test_an_anr_of_this_app_is_found_with_its_reason():
    from backend.android_evidence import app_problem
    lines = ["1731167200.1  900  950 E ActivityManager: ANR in com.example.shop (com.example.shop/.Main)",
             "1731167200.1  900  950 E ActivityManager: PID: 4321",
             "1731167200.1  900  950 E ActivityManager: Reason: Input dispatching timed out"]
    assert app_problem(lines, PACKAGE) == {"kind": "anr", "summary": "Input dispatching timed out"}


def test_the_saved_device_log_keeps_only_this_apps_lines(tmp_path, monkeypatch):
    from backend import android_evidence
    monkeypatch.setattr(android_evidence, "_adb", lambda: None)
    path = android_evidence.save_log(tmp_path, "android_case_1", CRASH_LOG, PACKAGE, "emulator-5554")
    saved = (tmp_path / path).read_text(encoding="utf-8")
    assert "Cart is null" in saved and "unrelated" not in saved
    with pytest.raises(ValueError):
        android_evidence.save_log(tmp_path, "../escape", CRASH_LOG, PACKAGE, "emulator-5554")


def test_a_recording_is_written_only_as_failure_evidence(tmp_path):
    import base64

    from backend.android_evidence import stop_recording
    driver = SimpleNamespace(stop_recording_screen=lambda: base64.b64encode(b"mp4-bytes").decode())
    assert stop_recording(driver, tmp_path, "case_ok", keep=False) is None
    assert stop_recording(driver, tmp_path, "case_bad", keep=True) == "videos/case_bad.mp4"
    assert (tmp_path / "videos" / "case_bad.mp4").read_bytes() == b"mp4-bytes"


def test_a_crash_is_reported_as_a_high_severity_app_defect(tmp_path):
    from backend.android_reporting import analyze, classify_failure
    result = {"id": "c", "outcome": "failed", "exception_type": "AppCrash", "error": "The app crashed during this test",
              "logcat": "logcat/c.txt", "video": "videos/c.mp4"}
    assert classify_failure(result) == "app_crash"
    failure = analyze({"run_dir": str(tmp_path), "test_cases": [], "results": [result]})["failures"][0]
    assert failure["severity"] == "high" and failure["logcat"] == "logcat/c.txt" and "device log" in failure["evidence"]


# ------------------------------------------------------------------ 7. features and report

def test_test_build_flows_count_as_functional_checks_and_appear_in_the_report(tmp_path):
    from backend.android_features import feature_matrix
    from backend.android_reporting import render_mobile_report

    session, screens = _session(FakeApp("shop"), tmp_path)
    session.run()
    cases = android_interact.auto_cases(session.flows)
    results = [{"id": c["id"], "outcome": "passed", "checks": 1, "auto_flow_id": c["auto_flow_id"]} for c in cases]
    features = feature_matrix({"test_cases": cases, "results": results, "screens": screens, "config": {},
                               "auto_flows": session.flows})
    assert features["functional_checks"]["configured"] == len(cases) == features["functional_checks"]["passed"]
    assert all(row["source"] == "test_build" for row in features["configured_features"])

    summary = {"counts": {"passed": 1, "failed": 0, "error": 0}, "verdict": "Ready", "screens_visited": 1,
               "self_healing_attempts": 0, "reasons": [], "gates": [], "coverage": {"tested": 1, "unvisited": []},
               "package_name": PACKAGE, "android_version": "16", "device_id": "emulator-5554", "run_id": "r",
               "interaction": {"enabled": True, "kept": len(session.flows), "tries_used": session.used,
                               "tried": session.tried, "findings": [{"screen": "Login", "finding": "Login with a wrong password was accepted", "detail": "x"}]},
               "user_like_tests": {"total": len(cases), "passed": len(cases), "failed": 0}, "app_crashes": 0}
    page = render_mobile_report(summary, [], [], [], screens, [])
    assert "User-like testing (test build)" in page and "Login with a wrong password was accepted" in page
    assert "User-like tests passed" in page and 'href="auto_flows.json"' in page


def test_reset_app_data_gives_back_only_runtime_permissions():
    calls = []

    class Driver:
        def execute_script(self, name, args):
            calls.append((name, args))
            if name == "mobile: getPermissions":
                return ["android.permission.INTERNET", "android.permission.CAMERA", "android.permission.POST_NOTIFICATIONS"]
            return None

        def activate_app(self, package):
            calls.append(("activate", package))

    android.reset_app_data(Driver(), PACKAGE)
    granted = [args["permissions"][0] for name, args in calls if name == "mobile: changePermissions"]
    assert granted == ["android.permission.CAMERA", "android.permission.POST_NOTIFICATIONS"]
    assert calls[1][0] == "mobile: clearApp" and calls[-1] == ("activate", PACKAGE)
    with pytest.raises(AndroidEnvironmentError):
        android.reset_app_data(Driver(), "not a package")
