"""Trusted execution of approved application contracts; shared by browser and Android adapters."""

import inspect
import json
import os
import re
import time
from pathlib import Path

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from .qa_contracts import (
    contract_case_budget,
    displayed_number,
    evaluate,
    finite_decimal,
    origin,
    parse_contract,
    protected,
)
from .qa_oracles import check_http, check_sqlite
from .safety import redact


class ControlMissing(AssertionError):
    """An expected control could not be found at all (hidden by the keyboard, scrolled away, or really gone). Kept
    apart from a control that was found with the wrong text or state: only the caller knows whether it is a finding."""


class ContractRuntime:
    def __init__(self, adapter, contract, private_inputs=None):
        self.adapter = adapter
        self.contract = parse_contract(contract)
        self.private = private_inputs or {"secrets": {}, "databases": {}}
        self.checks = 0
        self.evidence = []
        self.steps = []
        self.sensitive = False
        self.authentication_verified = False
        self.rotated = False
        self.timeout_s = 90
        self.deadline = time.monotonic() + self.timeout_s

    def _budget(self):
        if time.monotonic() > self.deadline:
            raise TimeoutError(f"The approved flow exceeded its {self.timeout_s} second limit")
        self.adapter.guard()

    def _blocked(self, identity: str, navigation: bool = False) -> bool:
        """The live control is checked again: test-mode rules only for a test-mode contract on an adapter that is
        itself in test mode (Android test mode, re-confirmed for this run); otherwise the strict rule. A test-mode
        navigation tap (opening an app's own screen) skips only the device-feature words."""
        test_mode = self.contract.test_mode and getattr(self.adapter, "test_mode", False)
        native = getattr(self.adapter, "active", "native") != "webview" and not (test_mode and navigation)
        return bool(protected(identity, test_mode, native=native))

    def _find(self, locator, optional=False):
        # Simple adapters (and older ones) take only the locator: for them a missing control raises, which an
        # optional lookup turns into None.
        if not optional:
            return self.adapter.find(locator)
        if "optional" in inspect.signature(self.adapter.find).parameters:
            return self.adapter.find(locator, optional=True)
        try:
            return self.adapter.find(locator)
        except NoSuchElementException:
            return None

    def _flow(self, flow_id):
        flow = next(f for f in self.contract.flows if f.id == flow_id)
        if not self.contract.test_environment or not flow.approved:
            raise ValueError("This flow and its test environment must be approved")
        if flow.setup_flow:
            self._flow(flow.setup_flow)
        for index, step in enumerate(flow.steps, 1):
            self._budget()
            if isinstance(self.adapter, AndroidContractAdapter):
                self.adapter.permissions.before_step(step.action)
            if step.action in {'permission_state', 'handle_permission', 'assert_permission'}:
                if not isinstance(self.adapter, AndroidContractAdapter):
                    raise ValueError('Android permission steps require native emulator testing')
                if step.action == 'permission_state':
                    self.adapter.permissions.set_state(step.permission, step.value)
                elif step.action == 'handle_permission':
                    self.evidence.append({'contract_id': flow.id, 'kind': 'permission_prompt',
                                          **self.adapter.permissions.handle(step.permission, step.value)})
                    self.checks += 1
                else:
                    self.adapter.permissions.assert_state(step.permission, step.value)
                    self.checks += 1
            elif step.action == 'relaunch':
                if not isinstance(self.adapter, AndroidContractAdapter):
                    raise ValueError('App relaunch steps require native Android testing')
                self.adapter.relaunch()
            elif step.action == "context":
                self.adapter.context(step.value)
            elif step.action == "open":
                opener = getattr(self.adapter, "open", None)
                if opener is None:
                    raise ValueError("Open steps need a browser (Android Chrome or a website run)")
                opener(step.value)
            elif step.action == "assert_alert":
                reader = getattr(self.adapter, "alert_text", None)
                if reader is None:
                    raise ValueError("Browser-message checks need Android Chrome")
                shown = reader(min(8.0, max(0.0, self.deadline - time.monotonic())))
                assert shown is not None, f"Expected the browser message {step.value!r}; no message appeared."
                assert shown.strip() == step.value.strip(), f"Expected the browser message {step.value!r}; found {shown[:200]!r}."
                self.checks += 1
            elif step.action in ("back", "rotate", "background", "hide_keyboard"):
                device = getattr(self.adapter, "device_action", None)
                if device is None:
                    raise ValueError("Back, rotate, background and hide_keyboard steps require Android testing")
                if step.action == "rotate":
                    self.rotated = self.rotated or step.value != "portrait"
                device(step.action, step.value)
            elif step.action == "assert_screen":
                self.adapter.assert_screen(step.value)
                self.checks += 1
            elif step.action == "assert_not_visible":
                # A closing dialog or a list update can take a moment: wait (bounded) for it to go.
                deadline = min(self.deadline, time.monotonic() + 5)
                while self._find(step.locator, optional=True) and time.monotonic() < deadline:
                    self._budget()
                    time.sleep(.2)
                assert not self._find(step.locator, optional=True), (
                    "The configured control should not be visible."
                )
                self.checks += 1
            else:
                # A missing control is a failed visibility/state assertion; an ambiguous locator
                # remains an automation error. Keeping these separate prevents locator problems
                # from being reported as app defects, while making missing UI real test evidence.
                optional_assertion = step.action in ("assert_visible", "assert_text", "assert_enabled", "assert_checked")
                element = self._find(step.locator, optional=optional_assertion)
                if step.action == 'request_permission':
                    if not isinstance(self.adapter, AndroidContractAdapter):
                        raise ValueError('Android permission requests require native emulator testing')
                    self.adapter.permissions.request(element, step.permission, self.adapter.identity(element), step.permissions)
                elif step.action in ("swipe", "drag", "scroll_to"):
                    # A web page scrolls as a whole (its container is <html>, whose words are the whole page): only
                    # the control scrolled to is checked there, and again when it is tapped.
                    web_scroll = step.action == "scroll_to" and getattr(self.adapter, "active", "") == "webview"
                    identities = [] if web_scroll else [self.adapter.identity(element)]
                    if step.target:
                        identities.append(step.target.value)
                    target = self.adapter.find(step.target) if step.action == "drag" else None
                    if target is not None:
                        identities.append(self.adapter.identity(target))
                    if any(self._blocked(identity) for identity in identities):
                        raise ValueError("Blocked a gesture on an irreversible control")
                    if step.action == "swipe":
                        self.adapter.swipe(element, step.value)
                    elif step.action == "scroll_to":
                        attempts = self.adapter.scroll_to(element, step.target, step.value)
                        self.evidence.append({"contract_id":flow_id,"kind":"bounded_scroll","attempts":attempts})
                    else:
                        self.adapter.drag(element, target)
                elif step.action == "long_press":
                    identity = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", self.adapter.identity(element)).replace("_", " ")
                    if self._blocked(identity):
                        raise ValueError("Blocked an irreversible live control")
                    if not hasattr(self.adapter, "long_press"):
                        raise ValueError("Long-press steps require native Android testing")
                    self.adapter.long_press(element)
                elif step.action == "tap":
                    identity = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", self.adapter.identity(element)).replace("_", " ")
                    if self._blocked(identity, navigation=step.purpose == "navigation"):
                        raise ValueError("Blocked an irreversible live control")
                    opens_login_screen = bool(
                        re.search(r"\b(open|go to)\s+(the\s+)?(login|log in|sign in)\s+(screen|page)\b", identity, re.I)
                    )
                    if (
                        step.purpose == "navigation"
                        and not opens_login_screen
                        and re.search(r"\b(login|log in|sign in|submit|register|save|create|add)\b", identity, re.I)
                    ):
                        raise ValueError("A form submission must be explicitly marked test_form")
                    assert self.adapter.enabled(element), "The configured action is disabled."
                    self.adapter.tap(element)
                elif step.action == "fill":
                    self.sensitive = True  # Filled forms never enter screenshots or model input.
                    value = self.private["secrets"][step.secret_ref] if step.secret_ref else step.value
                    try:
                        self.adapter.fill(element, value)
                    except Exception as error:
                        if isinstance(self.adapter, AndroidContractAdapter):
                            from .android_runtime import device_unavailable

                            if device_unavailable(error):
                                raise RuntimeError("Android device/session is unavailable during the input step.") from None
                        raise RuntimeError(f"The configured input step failed ({type(error).__name__}); entered values were omitted.") from None
                elif step.action == "assert_text":
                    deadline = min(self.deadline, time.monotonic() + 8)
                    actual = ""
                    while True:
                        self._budget()
                        try:
                            if element is not None and self.adapter.input_sensitive(element):
                                raise ValueError("Input contents cannot be asserted as report text")
                            actual = self.adapter.text(element) if element is not None else ""
                            if element is not None and actual == step.value:
                                break
                        except StaleElementReferenceException:
                            pass
                        if time.monotonic() >= deadline:
                            detail = "control was not visible" if element is None else f"found {actual[:200]!r}"
                            raise AssertionError(f"Expected text {step.value!r}; {detail}.")
                        time.sleep(.15)
                        element = self._find(step.locator, optional=True)
                    self.checks += 1
                elif step.action == "select":
                    self.adapter.select(element, step.value)
                    self.checks += 1
                elif step.action == "assert_visible":
                    # A dialog fading in or a result arriving after a request: wait (bounded) for it to appear.
                    deadline = min(self.deadline, time.monotonic() + 5)
                    uncover = getattr(self.adapter, "uncover", None)
                    if element is None and uncover and uncover():  # the soft keyboard was covering it
                        element = self._find(step.locator, optional=True)
                    while element is None and time.monotonic() < deadline:
                        self._budget()
                        time.sleep(.2)
                        element = self._find(step.locator, optional=True)
                    if element is None:
                        raise ControlMissing("The configured control is not visible.")
                    assert self.adapter.visible(element), "The configured control is not visible."
                    self.checks += 1
                elif step.action == "assert_enabled":
                    expected = (step.value or "true").lower() == "true"
                    assert element is not None and self.adapter.enabled(element) == expected, (
                        "Control enabled state does not match the configured expectation."
                    )
                    self.checks += 1
                elif step.action == 'assert_checked':
                    expected = (step.value or 'true') == 'true'
                    deadline = min(self.deadline, time.monotonic() + 8)
                    while element is not None and self.adapter.checked(element) != expected and time.monotonic() < deadline:
                        time.sleep(.2)
                        element = self._find(step.locator, optional=True)
                    assert element is not None and self.adapter.checked(element) == expected, 'Control checked state does not match the expected result'
                    self.checks += 1
            self.steps.append({"text": f"{flow.id}: step {index} {step.action}", "ok": True})
        if flow.authentication:
            self.authentication_verified = True

    def execute(self, contract_id):
        if not self.contract.test_environment:
            raise ValueError("The configured test environment is not approved")
        self.timeout_s = contract_case_budget(self.contract, contract_id)
        self.deadline = time.monotonic() + self.timeout_s
        try:
            if any(f.id == contract_id for f in self.contract.flows):
                self._flow(contract_id)
            elif any(r.id == contract_id for r in self.contract.rules):
                rule = next(r for r in self.contract.rules if r.id == contract_id)
                if rule.setup_flow:
                    self._flow(rule.setup_flow)
                self._budget()
                variables = {
                    key: displayed_number(self.adapter.text(self.adapter.find(source.locator)))
                    if source.locator
                    else finite_decimal(source.number)
                    for key, source in rule.variables.items()
                }
                actual = displayed_number(self.adapter.text(self.adapter.find(rule.actual)))
                expected = evaluate(rule.expression, variables)
                self.evidence.append(
                    {
                        "contract_id": rule.id,
                        "kind": "business_rule",
                        "expected": str(expected),
                        "actual": str(actual),
                        "expression": rule.expression,
                    }
                )
                assert abs(actual - expected) <= finite_decimal(rule.tolerance), (
                    f"Business rule {rule.id}: expected {expected}, found {actual}."
                )
                self.checks += 1
            else:
                check = next(c for c in self.contract.checks if c.id == contract_id)
                if check.setup_flow:
                    self._flow(check.setup_flow)
                self._budget()
                record = (
                    check_http(check, self.contract.allowed_origins, self.private["secrets"])
                    if check.kind == "http"
                    else check_sqlite(check, self.private["databases"])
                )
                self.evidence.append({"contract_id": check.id, **record})
                self.checks += 1
        except Exception as error:
            message = redact(str(error), list(self.private["secrets"].values()))
            if isinstance(error, AssertionError):
                # The kind of failure travels with it (ControlMissing vs. a wrong value); secrets are removed.
                raise type(error)(message) from None
            raise RuntimeError(message) from None
        finally:
            try:
                if self.rotated:
                    try:  # the next test must start in the normal orientation, even after a failure
                        self.adapter.device_action("rotate", "portrait")
                    except Exception:
                        pass
                if isinstance(self.adapter, AndroidContractAdapter):
                    restored = self.adapter.permissions.restore()
                    if restored:
                        self.evidence.append({'contract_id': contract_id, 'kind': 'permission_cleanup', 'restored': restored})
            finally:
                self.adapter.context(getattr(self.adapter, "default_context", "native"))


class AndroidContractAdapter:
    def __init__(self, driver, config, contract, stop_path=None):
        if getattr(contract, 'android_package', None) and contract.android_package != config.get('package_name'):
            raise ValueError('The test-flow package does not match the selected Android application')
        self.driver, self.config, self.contract = driver, config, contract
        self.stop_path = Path(stop_path) if stop_path else None
        self.active = "webview" if config.get("app_mode") == "web" else "native"
        self.default_context = self.active
        from .android import interaction_blocker
        from .android_permissions import PermissionSession

        # Test-mode rules apply only while this run itself is in (allowed) test mode, never from the contract alone.
        self.test_mode = not interaction_blocker(config)
        self.permissions = PermissionSession(driver, config, getattr(contract, 'android_permissions', None), self.relaunch, self.stop_path)

    def guard(self):
        from .android import AndroidEnvironmentError

        if self.stop_path and self.stop_path.exists():
            raise InterruptedError("The approved Android flow was stopped by the user")

        if self.config.get("app_mode") == "web":
            from .android_web import current_url, guard_url
            guard_url(current_url(self.driver), self.config)
            return

        previous = self.driver.current_context
        if previous != "NATIVE_APP":
            self.driver.switch_to.context("NATIVE_APP")
        actual_package = self.driver.current_package
        if actual_package != self.config["package_name"] and not self.permissions.allows_foreground(actual_package):
            # The keyboard, or (in test mode) a permission prompt that is declined, is not leaving the app
            from .android import bring_app_back
            actual_package = bring_app_back(self.driver, self.config) or self.config["package_name"]
        if actual_package != self.config["package_name"] and not self.permissions.allows_foreground(actual_package):
            raise AndroidEnvironmentError(f"The contract left the selected Android application ({actual_package} "
                                          "came to the front)")
        if previous != "NATIVE_APP":
            self.driver.switch_to.context(previous)
            self._origin()

    def uncover(self) -> bool:
        """Hide the soft keyboard when it is shown (it can cover a form's boxes): True when it was hidden."""
        if self.active != "native":
            return False
        try:
            if self.driver.is_keyboard_shown():
                self.driver.hide_keyboard()
                return True
        except Exception:
            return False
        return False

    def relaunch(self):
        if self.stop_path and self.stop_path.exists():
            raise InterruptedError('The Android relaunch was stopped by the user')
        if self.active != 'native' or self.config.get('app_mode') == 'web':
            raise ValueError('App relaunch requires native Android testing')
        from .android import AndroidEnvironmentError, inspect_driver
        from .android_runtime import settled_screen

        package = self.config['package_name']
        self.driver.terminate_app(package)
        self.driver.activate_app(package)
        deadline = time.monotonic() + 30
        while self.driver.current_package != package:
            if time.monotonic() >= deadline:
                raise AndroidEnvironmentError('The selected Android app did not return after relaunch')
            time.sleep(.25)
        settled_screen(lambda: inspect_driver(self.driver, self.config), timeout=max(1, deadline - time.monotonic()))

    def _origin(self):
        if origin(self.driver.current_url) not in {origin(u) for u in self.contract.allowed_origins}:
            raise ValueError("The WebView left the explicitly approved origins")

    def context(self, target):
        if self.config.get("app_mode") == "web":
            if target != "webview":
                raise ValueError("Android Chrome flows stay in browser context")
            self.guard()
            return
        if target == "native":
            self.driver.switch_to.context("NATIVE_APP")
            self.active = "native"
            return
        self.guard()
        expected = "WEBVIEW_" + self.config["package_name"]
        deadline = time.monotonic() + 10
        candidates = []
        while time.monotonic() < deadline:
            candidates = [c for c in self.driver.contexts if c == expected or c.startswith(expected + ":")]
            if candidates:
                break
            time.sleep(0.25)
        if len(candidates) != 1:
            raise RuntimeError("Exactly one debuggable WebView belonging to the selected app is required")
        self.driver.switch_to.context(candidates[0])
        self.active = "webview"
        self._origin()

    def find(self, locator, optional=False):
        self.guard()
        strategy = locator.strategy
        deadline = time.monotonic() + (0 if optional else 8)
        if self.active == "webview":
            if strategy != "css":
                raise ValueError("WebView contracts require CSS locators")
            using, value = "css selector", locator.value
        else:
            if strategy == "css":
                raise ValueError("CSS locators require a WebView context")
            from appium.webdriver.common.appiumby import AppiumBy

            strategies = {
                "accessibility_id": AppiumBy.ACCESSIBILITY_ID,
                "resource_id": AppiumBy.ID,
                "text": AppiumBy.ANDROID_UIAUTOMATOR,
                "xpath": AppiumBy.XPATH,
            }
            value = "new UiSelector().text(" + json.dumps(locator.value) + ")" if strategy == "text" else locator.value
            using = strategies[strategy]
        while True:
            self.guard()
            if self.config.get("app_mode") == "web":
                from .android_web import alert_safe
                matches = alert_safe(self.driver, lambda: [e for e in self.driver.find_elements(using, value)
                                                           if e.is_displayed()])
            else:
                matches = [e for e in self.driver.find_elements(using, value) if e.is_displayed()]
            if not matches and self.active == "native":
                from .android import recover_system_ui
                if recover_system_ui(self.driver):
                    continue
            if matches or time.monotonic() >= deadline:
                break
            time.sleep(.2)
        if not matches and optional:
            return None
        if len(matches) != 1:
            raise NoSuchElementException("The contract locator must select exactly one visible control")
        return matches[0]

    def assert_screen(self, title):
        from .android import inspect_driver

        if self.config.get("app_mode") == "web":
            from .android_web import alert_safe
            # The new page may still be loading after a tap: wait (bounded) for its title.
            deadline = time.monotonic() + 8
            while True:
                self.guard()
                if alert_safe(self.driver, lambda: self.driver.title or "").casefold() == title.casefold():
                    return
                if time.monotonic() > deadline:
                    raise AssertionError("Expected browser title was not reached.")
                time.sleep(.2)
        assert self.active == "native", "Screen-title assertions require the native context."
        deadline = time.monotonic() + 5
        while True:
            if inspect_driver(self.driver, self.config)["screen_name"].casefold() == title.casefold():
                return
            if time.monotonic() > deadline:
                raise AssertionError("Expected native screen " + title + " was not reached.")
            time.sleep(0.2)

    def identity(self, element):
        if self.active == "webview":
            # A button's words can be in its title or (for <input type=submit>) its value, a link's in its address.
            keys = ("id", "name", "aria-label", "type", "title", "href")
            words = [element.text or "", *[(element.get_attribute(k) or "") for k in keys]]
            if (element.get_attribute("type") or "").lower() in ("submit", "button", "reset", "image"):
                words.append(element.get_attribute("value") or "")
            return " ".join(words)
        keys = ("resource-id", "content-desc")
        return " ".join([element.text or "", *[(element.get_attribute(k) or "") for k in keys]])

    def input_sensitive(self, element):
        if self.active == "webview":
            return (element.get_property("tagName") or "").lower() in ("input", "textarea")
        return (
            str(element.get_attribute("password")).lower() == "true"
            or "edittext" in (element.get_attribute("class") or "").lower()
        )

    def tap(self, element):
        if self.active == "webview":
            from selenium.common.exceptions import ElementClickInterceptedException

            # Like a user: bring the control into view first (a sticky header can cover it near the screen edge),
            # and give a closing banner a moment before trying once more. Never a script click past an overlay.
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", element)
            try:
                element.click()
            except ElementClickInterceptedException:
                time.sleep(1)
                element.click()
            time.sleep(0.3)
            return
        element.click()
        time.sleep(0.2)

    def open(self, url):
        """Open a page of the approved website in Android Chrome (a user typing or following its address)."""
        if self.config.get("app_mode") != "web":
            raise ValueError("Open steps need Android Chrome")
        from .android_web import alert_safe, guard_url

        guard_url(url, self.config)
        alert_safe(self.driver, lambda: self.driver.get(url))
        self.guard()

    def alert_text(self, wait_s=8.0):
        """The browser message (JavaScript alert) shown after the last action, closed with OK; None if none came.
        A message that would confirm checkout, payment or an account deletion is dismissed instead."""
        if self.config.get("app_mode") != "web":
            raise ValueError("Browser-message checks need Android Chrome")
        from .android_web import take_alert

        return take_alert(self.driver, wait_s)

    def fill(self, element, value):
        element.clear()
        # W3C sendKeys rejects an empty value on real UiAutomator2. Clearing is
        # the intended operation for a required-field/empty-input scenario.
        if value:
            element.send_keys(value)
        if self.active == "webview" and element.get_property("value") != value:
            raise AssertionError("The browser input did not retain the supplied value; contents omitted")
        if self.active == "native" and str(element.get_attribute("password")).lower() != "true":
            actual = element.text
            # Android accessibility can expose the placeholder as text after
            # clearing. Its showing-hint flag distinguishes that from retained input.
            if value == '' and str(element.get_attribute('showing-hint')).lower() == 'true':
                actual = ''
            if actual != value:
                raise AssertionError("The input did not retain the supplied value; contents omitted")
        if self.active == "native" and self.driver.is_keyboard_shown():
            self.driver.hide_keyboard()

    def select(self, element, value):
        if self.active != "webview":
            raise ValueError("Select steps require a browser context; native lists use approved tap steps")
        from selenium.webdriver.support.ui import Select
        options = Select(element)
        options.select_by_value(value)
        try:
            assert options.first_selected_option.get_attribute("value") == value, "Dropdown selection was not retained"
        except StaleElementReferenceException:
            time.sleep(.5)  # the website answered the choice with a new page (sort order, page size): it was taken

    def device_action(self, action, value=None):
        """Phone-level actions a manual tester uses: the system Back button, rotation, leaving and resuming the app."""
        if self.stop_path and self.stop_path.exists():
            raise InterruptedError("The approved Android flow was stopped by the user")
        if action == "back":
            self.driver.back()
            time.sleep(.5)
        elif action == "rotate":
            self.driver.orientation = value.upper()
            time.sleep(1.2)  # the activity may be recreated; finds below wait for its controls
        elif action == "background":
            if self.config.get("app_mode") == "web":
                raise ValueError("Background/resume steps require a native Android app")
            self.driver.background_app(int(value))  # returns after the app was brought back
            from .android import AndroidEnvironmentError
            deadline = time.monotonic() + 15
            while self.driver.current_package != self.config["package_name"]:
                if time.monotonic() >= deadline:
                    raise AndroidEnvironmentError("The app did not come back after being sent to the background")
                time.sleep(.25)
            time.sleep(.5)
        elif action == "hide_keyboard":
            if self.active == "native" and self.driver.is_keyboard_shown():
                self.driver.hide_keyboard()
        else:
            raise ValueError("Unknown device action")
        self.guard()

    def long_press(self, element):
        if self.active != "native":
            raise ValueError("Long-press currently requires the native Android context")
        self.driver.execute_script("mobile: longClickGesture", {"elementId": element.id, "duration": 1000})
        time.sleep(.4)

    def swipe(self, element, direction):
        if self.active != "native":
            raise ValueError("Approved gestures currently require the native Android context")
        self.driver.execute_script("mobile: swipeGesture", {"elementId": element.id, "direction": direction, "percent": .7})
        time.sleep(.4)

    def drag(self, element, target):
        if self.active != "native":
            raise ValueError("Approved gestures currently require the native Android context")
        bounds = target.rect
        self.driver.execute_script("mobile: dragGesture", {"elementId": element.id,
            "endX": int(bounds["x"] + bounds["width"] / 2), "endY": int(bounds["y"] + bounds["height"] / 2), "speed": 700})
        time.sleep(.4)

    def scroll_to(self, container, target, direction):
        """Seek a declared target without scrolling outside its observed native container."""
        if self.active == "webview" and self.config.get("app_mode") == "web":
            # A web page scrolls as one: bring the recorded control below the screen edge into view, like a swipe.
            element = self.find(target)
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", element)
            time.sleep(.3)
            return 1
        if self.active != "native":
            raise ValueError("Scroll-to-target currently requires native Android testing")
        deadline = time.monotonic() + 45
        for attempt in range(9):
            self.guard()
            if self.find(target, optional=True) is not None:
                return attempt
            if attempt == 8 or time.monotonic() >= deadline:
                break
            bounds = container.rect
            if attempt % 2:
                area = {"left":int(bounds["x"] + bounds["width"]*.01),
                        "top":int(bounds["y"] + bounds["height"]*.03),
                        "width":max(1,int(bounds["width"]*.98)),
                        "height":max(1,int(bounds["height"]*.45))}
            else:
                area = {"elementId":container.id}
            self.driver.execute_script("mobile: swipeGesture", {**area,"direction":direction,"percent":.7,"speed":700})
            time.sleep(.3)
        raise NoSuchElementException("The declared scroll target was not reached within eight bounded gestures")

    @staticmethod
    def text(element):
        return element.text

    @staticmethod
    def enabled(element):
        return element.is_enabled()

    def checked(self, element):
        if self.active == "webview":
            # A web check box or radio button: its own selected state
            if (element.get_attribute("type") or "").lower() not in ("checkbox", "radio"):
                raise ValueError('Checked-state assertions require a checkbox, switch or radio control')
            return bool(element.is_selected())
        checkable = str(element.get_attribute('checkable')).lower() == 'true'
        kind = element.get_attribute('class') or ''
        if not checkable and not kind.endswith(('Switch', 'CheckBox', 'RadioButton', 'ToggleButton')):
            raise ValueError('Checked-state assertions require a checkbox, switch or radio control')
        return str(element.get_attribute('checked')).lower() == 'true'

    @staticmethod
    def visible(element):
        return element.is_displayed()


def private_inputs(run_dir):
    encoded = os.environ.get("ANDROID_CONTRACT_INPUTS", "")
    if encoded:
        return json.loads(encoded)
    path = Path(run_dir) / ".private" / "contract_inputs.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"secrets": {}, "databases": {}}
