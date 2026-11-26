"""iOS apps (native and hybrid) through Appium's XCUITest driver - on the same orchestration, reporting and traceability
as the other engines (a Jira execution with target type "ios" runs here).

  environment   what a real iOS run needs, each checked and named when missing: macOS with Xcode (xcrun), a simulator
                (booted) or an authorized device (UDID), an Appium 2 server with the 'xcuitest' driver, the app (a
                .app / .ipa file, or a bundle id already installed) and, for a device, a signing team
                (xcodeOrgId / updatedWDABundleId). Missing -> the run is refused with exactly what to provide (BLOCKED).
  capabilities  XCUITest options from the config (never a password)
  screen        the XCUI hierarchy -> the controls a person sees: type, name (accessibility id), label, value,
                enabled / visible, place - so steps are planned from the real screen, not guessed
  steps         tap / type / clear / assert_visible / assert_text / assert_not_visible / swipe / back - each found by
                accessibility id, label, name or (in a WebView) CSS; the context is chosen per step (CSS -> the app's
                WebView context, others -> NATIVE_APP) and recorded; a WebView that is not inspectable is reported
                (it must be a debuggable / WKWebView with isInspectable on iOS 16.4+)
  results       every step with what it found, a screenshot per case, and the case's outcome (Passed / Failed /
                Blocked / Not automated with the reason) in the run's test_cases.json - the same format the other
                engines write
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, Field

BUNDLE_ID = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
UDID = re.compile(r"^[A-Fa-f0-9-]{20,60}$")


class IosConfig(BaseModel):
    udid: str = Field(default="", max_length=60)  # a simulator's or a device's UDID ('' = the booted simulator)
    bundle_id: str = Field(default="", max_length=200)
    app_path: str = Field(default="", max_length=1000)  # a .app (simulator) / .ipa (device) to install
    platform_version: str = Field(default="", max_length=10)
    device_name: str = Field(default="iPhone 15", max_length=80)
    real_device: bool = False
    xcode_org_id: str = Field(default="", max_length=20)  # (a real device: the signing team of the WebDriverAgent)
    wda_bundle_id: str = Field(default="", max_length=200)
    appium_url: str = Field(default="http://127.0.0.1:4723", max_length=300)


def validate(config: dict) -> IosConfig:
    c = IosConfig.model_validate(config or {})
    if not c.bundle_id and not c.app_path:
        raise ValueError("Give the app's bundle id (e.g. com.example.app) or a .app / .ipa file to install.")
    if c.bundle_id and not BUNDLE_ID.match(c.bundle_id):
        raise ValueError("A bundle id looks like com.example.app.")
    if c.app_path and not c.app_path.lower().endswith((".app", ".ipa", ".zip")):
        raise ValueError("The app file must be a .app (simulator), .ipa (device) or a zipped .app.")
    if c.udid and not UDID.match(c.udid):
        raise ValueError("A UDID is 20-60 hex characters and dashes.")
    if c.real_device and not (c.udid and c.xcode_org_id):
        raise ValueError("A real iOS device needs its UDID and the signing team id (xcodeOrgId) of the "
                         "WebDriverAgent.")
    return c


def capabilities(c: IosConfig) -> dict:
    caps = {"platformName": "iOS", "appium:automationName": "XCUITest", "appium:deviceName": c.device_name,
            "appium:newCommandTimeout": 120, "appium:autoAcceptAlerts": False, "appium:includeSafariInWebviews": False,
            "appium:webviewConnectTimeout": 10000}
    if c.udid:
        caps["appium:udid"] = c.udid
    if c.platform_version:
        caps["appium:platformVersion"] = c.platform_version
    if c.app_path:
        caps["appium:app"] = c.app_path
    if c.bundle_id:
        caps["appium:bundleId"] = c.bundle_id
    if c.real_device:
        caps["appium:xcodeOrgId"] = c.xcode_org_id
        caps["appium:xcodeSigningId"] = "Apple Development"
        if c.wda_bundle_id:
            caps["appium:updatedWDABundleId"] = c.wda_bundle_id
    return caps


def environment_problems(c: IosConfig, run=subprocess.run, http_get=None) -> list[str]:
    """Everything a real iOS run needs that this machine does not have - each said plainly ([] = ready)."""
    problems = []
    if platform.system() != "Darwin":
        problems.append(f"iOS testing needs macOS with Xcode; this Studio runs on {platform.system()}. Run the Studio "
                        "(or its Appium server) on a Mac.")
    elif not shutil.which("xcrun"):
        problems.append("Xcode's command line tools are missing (xcrun): install Xcode and run 'xcode-select "
                        "--install'.")
    elif not c.real_device:
        try:
            booted = run(["xcrun", "simctl", "list", "devices", "booted"], capture_output=True, text=True, timeout=20)
            if "Booted" not in booted.stdout and not c.udid:
                problems.append("No iOS simulator is booted: start one in Xcode (or 'xcrun simctl boot <udid>').")
        except (OSError, subprocess.TimeoutExpired):
            problems.append("The iOS simulators could not be listed (xcrun simctl).")
    try:
        import httpx
        status = (http_get or (lambda u: httpx.get(u, timeout=5).json()))(c.appium_url.rstrip("/") + "/status")
        if not (status or {}).get("value", {}).get("ready", True):
            problems.append(f"The Appium server at {c.appium_url} is not ready.")
    except Exception:
        problems.append(f"No Appium server answers at {c.appium_url}: start Appium 2 ('appium') with the XCUITest "
                        "driver ('appium driver install xcuitest').")
    return problems


# ---------------------------------------------------------------- the screen

def screen(page_source: str, limit: int = 120) -> list[dict]:
    """The controls of the XCUI hierarchy a person can see (visible elements with a name / label / value)."""
    from defusedxml import ElementTree
    out = []
    try:
        root = ElementTree.fromstring(page_source or "<x/>")
    except Exception:
        return out
    for e in root.iter():
        a = e.attrib
        if a.get("visible", "true") == "false" or not (a.get("name") or a.get("label") or a.get("value")):
            continue
        kind = (a.get("type") or e.tag).replace("XCUIElementType", "")
        if kind in ("Application", "Window") or (kind == "Other" and not a.get("name")):
            continue  # (containers are not controls a person uses)
        out.append({"type": kind, "name": a.get("name") or "", "label": a.get("label") or "",
                    "value": (a.get("value") or "")[:120], "enabled": a.get("enabled", "true") == "true",
                    "at": [a.get(k) for k in ("x", "y", "width", "height")]})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- steps

class IosStep(BaseModel):
    action: str = Field(pattern=r"^(tap|type|clear|assert_visible|assert_not_visible|assert_text|swipe|back)$")
    by: str = Field(default="accessibility_id", pattern=r"^(accessibility_id|label|name|predicate|css)$")
    target: str = Field(default="", max_length=300)
    value: str = Field(default="", max_length=500)


class IosCase(BaseModel):
    case: str
    steps: list[IosStep] = Field(default_factory=list, max_length=40)
    not_possible: str = ""


class IosRun:
    """One Appium XCUITest session that runs the planned steps of each case and records the evidence."""

    def __init__(self, driver, run_dir: Path, bundle_id: str = ""):
        self.d, self.run_dir, self.bundle_id = driver, Path(run_dir), bundle_id
        self.context_switches: list[dict] = []

    def _context(self, by: str) -> None:
        want_web = by == "css"
        current = getattr(self.d, "current_context", "NATIVE_APP") or "NATIVE_APP"
        if want_web and not current.startswith("WEBVIEW"):
            webviews = [c for c in (self.d.contexts or []) if str(c).startswith("WEBVIEW")]
            if not webviews:
                raise RuntimeError("No inspectable WebView in the app on this screen (on iOS 16.4+ the WKWebView must "
                                   "set isInspectable = true in the test build)")
            self.d.switch_to.context(webviews[-1])
            self.context_switches.append({"to": webviews[-1], "because": "a CSS locator belongs to the WebView"})
        elif not want_web and current.startswith("WEBVIEW"):
            self.d.switch_to.context("NATIVE_APP")
            self.context_switches.append({"to": "NATIVE_APP", "because": f"a {by} locator belongs to native UI"})

    def _find(self, step: IosStep):
        from appium.webdriver.common.appiumby import AppiumBy
        self._context(step.by)
        how = {"accessibility_id": (AppiumBy.ACCESSIBILITY_ID, step.target),
               "name": (AppiumBy.NAME, step.target),
               "label": (AppiumBy.IOS_PREDICATE, f"label == {json.dumps(step.target)}"),
               "predicate": (AppiumBy.IOS_PREDICATE, step.target),
               "css": (AppiumBy.CSS_SELECTOR, step.target)}[step.by]
        deadline = time.monotonic() + 8
        while True:
            found = [e for e in self.d.find_elements(*how) if e.is_displayed()]
            if found or time.monotonic() > deadline:
                return found
            time.sleep(0.3)

    def run_case(self, plan: IosCase) -> dict:
        record = {"requirement_test": plan.case, "tc_id": plan.case, "steps": [], "evidence": []}
        if not plan.steps:
            record.update(execution_status="Not run", skip_reason="Not automated: " + (plan.not_possible or
                                                                                         "no iOS steps were planned"))
            return record
        if self.bundle_id:
            try:
                self.d.activate_app(self.bundle_id)
            except Exception:
                pass
        failed, checks = "", 0
        for i, step in enumerate(plan.steps, 1):
            text = f"{step.action} {step.by}={step.target}" + (f" '{step.value}'" if step.value and
                                                                step.action != "type" else "")
            try:
                if step.action == "back":
                    self.d.back()
                elif step.action == "swipe":
                    self.d.execute_script("mobile: swipe", {"direction": step.value or "up"})
                else:
                    found = self._find(step)
                    if step.action == "assert_not_visible":
                        checks += 1
                        if found:
                            failed = f"step {i}: {step.target} is visible"
                    elif not found:
                        failed = f"step {i}: no visible control {step.by}={step.target}"
                    elif len(found) > 1 and step.action in ("tap", "type", "clear"):
                        failed = f"step {i}: {len(found)} controls match {step.by}={step.target}"
                    elif step.action == "tap":
                        found[0].click()
                    elif step.action == "type":
                        found[0].send_keys(step.value)
                    elif step.action == "clear":
                        found[0].clear()
                    elif step.action == "assert_visible":
                        checks += 1
                    elif step.action == "assert_text":
                        checks += 1
                        shown = " ".join(str(found[0].get_attribute(k) or "") for k in ("label", "value", "name"))
                        if step.value.casefold() not in shown.casefold():
                            failed = f"step {i}: expected '{step.value}', the control shows '{shown[:120]}'"
            except Exception as error:
                failed = f"step {i}: {type(error).__name__}: {str(error)[:200]}"
            record["steps"].append(text + (" - FAILED" if failed else ""))
            if failed:
                break
        shot = self.run_dir / "screenshots" / f"{plan.case}.png"
        try:
            shot.parent.mkdir(exist_ok=True)
            self.d.get_screenshot_as_file(str(shot))
            record["evidence"].append(f"screenshots/{shot.name}")
        except Exception:
            pass
        if failed and not checks and ("no visible control" in failed or "controls match" in failed):
            record.update(execution_status="Failed", failure_category="Test mistake", actual_result=failed)
        elif failed:
            record.update(execution_status="Failed", failure_category="Assertion failure", actual_result=failed)
        elif not checks:
            record.update(execution_status="Not run", skip_reason="Not automated: the planned steps checked nothing")
        else:
            record.update(execution_status="Passed", actual_result=f"{checks} check(s) passed", check_count=checks)
        return record


def plan_cases(cases: list[dict], controls: list[dict], ask=None) -> list[IosCase]:
    """The AI turns each test case into steps over the REAL controls of the screen (only names / labels it shows)."""
    from .llm import LLMError, ask_structured
    ask = ask or ask_structured
    prompt = ("Turn each test case into iOS app steps using ONLY these controls of the app's current screen (find "
              "them by accessibility_id = name, or label; css only inside a WebView). Actions: tap, type (value), "
              "clear, assert_visible, assert_not_visible, assert_text (value), swipe (value up/down/left/right), back. "
              "Every case ends with assertions of its expected result. When the screen has no control for a case, "
              "give no steps and say why in not_possible. Return a JSON array of {case, steps, not_possible}.\n"
              "CONTROLS:\n" + json.dumps(controls[:120]) + "\nTEST CASES:\n"
              + json.dumps([{"id": c["id"], "title": c.get("title"), "steps": c.get("steps")} for c in cases]))
    try:
        plans = ask(prompt, list[IosCase] | IosCase, agent="ios", page="screen")
    except (LLMError, ValueError) as error:
        return [IosCase(case=c["id"], not_possible=f"the AI could not plan iOS steps ({str(error)[:120]})")
                for c in cases]
    plans = plans if isinstance(plans, list) else [plans]
    known = {c["id"] for c in cases}
    names = {x for c in controls for x in (c["name"], c["label"]) if x}
    out = []
    for p in plans:
        if p.case not in known:
            continue
        invented = [s.target for s in p.steps if s.by in ("accessibility_id", "label", "name") and s.target
                    and s.target not in names]
        out.append(p if not invented else IosCase(case=p.case, not_possible=f"the plan used controls the screen "
                                                                           f"does not show: {invented[:3]}"))
    return out + [IosCase(case=c["id"], not_possible="the AI gave no iOS steps for it")
                  for c in cases if c["id"] not in {p.case for p in out}]
