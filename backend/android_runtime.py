"""Trusted Appium adapter. Generated code can only execute its validated mobile plan."""

import time
from pathlib import Path

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from .android import AndroidEnvironmentError, find_unique, inspect_driver, safe_navigation_elements


def device_unavailable(error):
    """Recognize loss of the device/session, not ordinary assertion/locator failures."""
    import re
    if isinstance(error, (AssertionError, NoSuchElementException, StaleElementReferenceException)):
        return False
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if re.search(r"device ['\"]?[^\s'\"]+['\"]? not found|device.*offline|no connected.*device|could not find a connected android device|"
                     r"invalid session id|session.*(?:terminated|not found)|instrumentation.*not running|"
                     r"uiautomator2.*(?:not running|cannot be proxied)|connection refused|actively refused|"
                     r"failed to establish a new connection|android device/session is unavailable", str(error), re.I):
            return True
        # User-facing wrappers truncate long driver messages. Classification must
        # retain the original cause without copying its contents into the report.
        error = error.__cause__ or error.__context__
    return False


def screen_key(screen):
    identity = screen.get("identity")
    return (screen["package_name"], screen.get("activity"), tuple(identity)) if identity else screen["fingerprint"]


def read_only_case(case):
    plan = case.get("plan", [])
    return bool(plan and sum(method == "open_screen" for method, _ in plan) == 1
                and all(method in {"open_screen", "assert_visible", "assert_enabled", "assert_text", "assert_screen"}
                        for method, _ in plan))


def settled_screen(inspect, expected=None, timeout=8):
    """Require a rendered, non-loading hierarchy twice before recording/replaying it."""
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        screen = inspect()
        ready = not screen.get("loading") and any(e.get("visible") and e.get("locators") and
            (e.get("text") or e.get("accessibility_id") or e.get("clickable") or e.get("input_capable")) for e in screen["elements"])
        if ready and (expected is None or same_screen(screen, expected)):
            # The expected screen with the same stable identity is there: no need for a second identical frame
            if expected is not None and screen.get("identity") and screen["identity"] == expected.get("identity"):
                return screen
            if previous == screen["fingerprint"]:
                return screen
            previous = screen["fingerprint"]
        else:
            previous = None
        time.sleep(.25)
    name = expected.get("screen_name") if expected else "a stable rendered screen"
    raise AndroidEnvironmentError("Android did not settle on " + name + ".")


def same_screen(actual: dict, expected: dict) -> bool:
    if actual["package_name"] != expected["package_name"] or actual.get("activity") != expected.get("activity"):
        return False
    if actual["fingerprint"] == expected["fingerprint"]:
        return True
    if actual.get("identity") and expected.get("identity"):
        return actual["identity"] == expected["identity"]

    # Stable heading and another unchanged identifier allow locator repair on a changed hierarchy.
    def anchors(screen):
        return {e.get("resource_id") or e.get("accessibility_id") for e in screen["elements"]} - {None, ""}

    return actual["screen_name"] == expected["screen_name"] and bool(anchors(actual) & anchors(expected))


def same_element(original: dict, candidate: dict) -> bool:
    if candidate.get("class_name") != original.get("class_name"):
        return False
    return any(
        original.get(key) and original[key] == candidate.get(key) for key in ("resource_id", "accessibility_id")
    ) or bool(original.get("text") and original["text"] == candidate.get("text") and not original.get("input_capable"))


class MobileRuntime:
    def __init__(self, driver, config: dict, screens: list[dict], case: dict, run_dir: Path):
        self.driver, self.screens, self.case, self.run_dir = driver, screens, case, run_dir
        self.config = {**config, "package_name": screens[0]["package_name"]}
        self.elements = {e["id"]: (screen, e) for screen in screens for e in screen["elements"]}
        self.healing = []
        self.repaired = {}
        self.locator_resolutions = []
        self.checks = 0
        self.sensitive = False
        self.contract_evidence = []
        self.authentication_verified = False
        self.steps = []
        self.started = time.monotonic()

    def _inspect(self):
        if (self.run_dir / "STOP").exists():
            raise AndroidEnvironmentError("The mobile run was stopped by the user.")
        if time.monotonic() - self.started > 120:
            raise AndroidEnvironmentError("The Android case exceeded its 120 second action budget.")
        screen = inspect_driver(self.driver, self.config)
        self.note_declined()
        return screen

    def note_declined(self):
        """A permission prompt that test mode declined while this test ran: a step of the test, then it goes on."""
        declined = getattr(self.driver, "_blowai_declined", None)
        while declined:
            self.steps.append({"text": "Declined the Android permission prompt: " + str(declined.pop(0))[:120],
                               "ok": True})

    def _element(self, element_id):
        if element_id not in self.elements:
            raise ValueError("Undiscovered element reference")
        expected_screen, original = self.elements[element_id]
        actual = self._inspect()
        if not same_screen(actual, expected_screen):
            raise AndroidEnvironmentError("Unexpected screen while resolving an element.")
        locator = self.repaired.get(element_id) or original["locators"][0]
        try:
            return find_unique(self.driver, locator)
        except (NoSuchElementException, StaleElementReferenceException) as original_error:
            for alternative in original["locators"]:
                if alternative == locator:
                    continue
                try:
                    selected = find_unique(self.driver, alternative)
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
                self.locator_resolutions.append({"element_id":element_id,"locator":alternative,
                    "evidence":"A recorded alternative uniquely identified the visible control on the expected screen"})
                return selected
            if original.get('scroll_hint'):
                from .android_scroll import seek_observed

                self.driver._blowai_previous_read_only = False
                selected, used_locator, attempts = seek_observed(self.driver, expected_screen, original,
                                                               self.config, self.run_dir / 'STOP')
                self.locator_resolutions.append({'element_id': element_id, 'locator': used_locator,
                    'scroll_attempts': attempts, 'evidence': 'Recorded offscreen control reached with bounded native scrolling'})
                return selected
            candidates = [e for e in actual["elements"] if e.get("visible") and same_element(original, e)]
            if len(candidates) != 1:
                raise original_error
            for alternative in candidates[0]["locators"]:
                if alternative == locator or len(self.healing) >= 2:
                    continue
                record = {
                    "element_id": element_id,
                    "original_locator": locator,
                    "replacement_locator": alternative,
                    "evidence": "Unique live element with matching class and stable identity on the same screen",
                    "lookup_outcome": "failed",
                }
                self.healing.append(record)
                try:
                    recovered = find_unique(self.driver, alternative)
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
                record["lookup_outcome"] = "recovered"
                self.repaired[element_id] = alternative
                return recovered
            raise original_error

    def wait_for_start(self):
        """Do not send contract actions into a splash or partially replaced activity."""
        deadline = time.monotonic() + 30

        def inspect_started_app():
            # activate_app can return during the launcher's handoff. Wait for
            # the approved package without reading the launcher's hierarchy.
            if self.config.get("app_mode") != "web":
                from .android import bring_app_back

                expected = self.config["package_name"]
                while getattr(self.driver, "current_package", expected) != expected:
                    # The keyboard, or (test mode) a permission prompt an earlier test left in front, is cleared
                    if not bring_app_back(self.driver, self.config):
                        break
                    if (self.run_dir / "STOP").exists():
                        raise AndroidEnvironmentError("The mobile run was stopped by the user.")
                    if time.monotonic() >= deadline:
                        raise AndroidEnvironmentError("The selected Android app did not enter the foreground after launch.")
                    time.sleep(.25)
            return self._inspect()

        settled_screen(inspect_started_app, self.screens[0], timeout=30)

    def open_screen(self, screen_id):
        expected = next((s for s in self.screens if s["id"] == screen_id), None)
        if expected is None:
            raise ValueError("Undiscovered screen reference")
        if expected.get("authentication_flow_id"):
            # Authenticated screens are reachable only after the approved test
            # account flow. Replay it from the clean launch state before the
            # authenticated screen's relative navigation path.
            if not self.authentication_verified:
                settled_screen(self._inspect, self.screens[0])
                self.assert_flow(expected["authentication_flow_id"])
            auth_root = next((s for s in self.screens
                              if s.get("id") == expected.get("authentication_root_id")), None)
            if auth_root is None:
                raise ValueError("The authenticated screen is missing its recorded login root.")
            if same_screen(self._inspect(), expected):
                settled_screen(self._inspect, expected)
                self.steps.append({"text": "Verified authenticated screen " + expected["screen_name"], "ok": True})
                return
            settled_screen(self._inspect, auth_root, timeout=30)
        else:
            if same_screen(self._inspect(), expected):
                settled_screen(self._inspect, expected)
                self.steps.append({"text": "Verified screen " + expected["screen_name"], "ok": True})
                return
            if self.config.get("app_mode") == "web" and expected.get("open_by_url") and expected.get("web_url"):
                # A page the website explorer recorded: opened by its address, like a user typing it (same origin).
                from .android_web import alert_safe, guard_url

                guard_url(expected["web_url"], self.config)
                alert_safe(self.driver, lambda: self.driver.get(expected["web_url"]))
                settled_screen(self._inspect, expected, timeout=20)
                self.steps.append({"text": "Open " + expected["screen_name"], "ok": True})
                return
            settled_screen(self._inspect, self.screens[0])
        path = expected.get("path", [])
        for index, element_id in enumerate(path):
            self.tap(element_id)
            destination = self.elements[path[index + 1]][0] if index + 1 < len(path) else expected
            settled_screen(self._inspect, destination, timeout=15)
        settled_screen(self._inspect, expected)
        self.steps.append({"text": "Open " + expected["screen_name"], "ok": True})

    def tap(self, element_id):
        owner, original = self.elements[element_id]
        if original not in safe_navigation_elements(owner):
            raise AndroidEnvironmentError('Blocked: the recorded control is not approved safe navigation')
        element = self._element(element_id)
        live = self._inspect()
        candidates = [e for e in safe_navigation_elements(live) if same_element(original, e)]
        if len(candidates) > 1:
            for locator in original["locators"]:
                exact = [e for e in candidates if locator in e.get("locators", [])]
                if len(exact) == 1:
                    candidates = exact
                    break
        if len(candidates) != 1:
            raise AndroidEnvironmentError("Blocked: the live control is not uniquely identified safe navigation.")
        if not element.is_enabled():
            raise AndroidEnvironmentError("The navigation control is disabled.")
        element.click()
        time.sleep(0.25)
        self._inspect()
        self.steps.append(
            {"text": "Tap " + (original.get("text") or original.get("accessibility_id") or "navigation"), "ok": True}
        )

    def assert_visible(self, element_id):
        assert self._element(element_id).is_displayed(), "The discovered control is not visible."
        self.checks += 1
        self.steps.append({"text": "Control is visible", "ok": True})

    def assert_enabled(self, element_id, expected="true"):
        actual = self._element(element_id).is_enabled()
        wanted = str(expected).casefold() == "true"
        assert actual == wanted, f"Expected enabled state {wanted}, found {actual}."
        self.checks += 1

    def assert_text(self, element_id, expected):
        actual = self._element(element_id).text
        assert actual == expected, f"Expected text {expected!r}, found {actual!r}."
        self.checks += 1

    def assert_screen(self, expected):
        deadline = time.monotonic() + 5
        actual = self._inspect()
        while actual["screen_name"].casefold() != expected.casefold() and time.monotonic() < deadline:
            time.sleep(0.2)
            actual = self._inspect()
        assert actual["screen_name"].casefold() == expected.casefold(), (
            f"Expected screen '{expected}', found '{actual['screen_name']}'."
        )
        self.checks += 1
        self.steps.append({"text": "Expected screen " + expected, "ok": True})

    def assert_destination(self, screen_id):
        """Verify an observed navigation result without inventing a business requirement."""
        expected = next((screen for screen in self.screens if screen['id'] == screen_id), None)
        if expected is None:
            raise ValueError('Undiscovered navigation destination')
        settled_screen(self._inspect, expected, timeout=15)
        self.checks += 1
        self.steps.append({'text': 'Navigation matches observed destination ' + expected['screen_name'], 'ok': True})


    def assert_flow(self, flow_id):
        """A replay-verified test-build flow (android_interact.py), run by the same trusted contract runtime."""
        import json

        from .android import PACKAGE_NAME
        from .qa_contracts import parse_contract
        from .qa_runtime import AndroidContractAdapter, ContractRuntime, private_inputs

        path = self.run_dir / ".private" / "auto_contract.json"
        if not path.is_file():
            raise ValueError("The test-build flows of this run are missing")
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Older runs may have android_package corrupted by username substring redaction.
        package = self.config.get("package_name")
        current = raw.get("android_package") if isinstance(raw, dict) else None
        if isinstance(raw, dict) and isinstance(package, str) and PACKAGE_NAME.fullmatch(package):
            if not isinstance(current, str) or "[REDACTED]" in current or not PACKAGE_NAME.fullmatch(current):
                raw["android_package"] = package
        contract = parse_contract(raw)
        if flow_id not in {flow.id for flow in contract.flows}:
            raise ValueError("Unknown test-build flow")
        runtime = ContractRuntime(AndroidContractAdapter(self.driver, self.config, contract, stop_path=self.run_dir / "STOP"),
                                  contract.model_dump(), private_inputs(self.run_dir))
        try:
            runtime.execute(flow_id)
        finally:
            self.checks += runtime.checks
            self.sensitive = self.sensitive or runtime.sensitive
            self.contract_evidence.extend(runtime.evidence)
            self.steps.extend(runtime.steps)
            self.authentication_verified = self.authentication_verified or runtime.authentication_verified

    def assert_contract(self, contract_id):
        from .qa_contracts import parse_contract
        from .qa_runtime import AndroidContractAdapter, ContractRuntime, private_inputs

        contract = parse_contract(self.config.get("qa_contract"))
        runtime = ContractRuntime(AndroidContractAdapter(self.driver, self.config, contract, stop_path=self.run_dir / "STOP"), contract.model_dump(), private_inputs(self.run_dir))
        try:
            runtime.execute(contract_id)
        finally:
            self.checks += runtime.checks
            self.sensitive = self.sensitive or runtime.sensitive
            self.contract_evidence.extend(runtime.evidence)
            self.steps.extend(runtime.steps)
            self.authentication_verified = runtime.authentication_verified
