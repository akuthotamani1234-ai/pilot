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
            if booted.returncode:
                problems.append("iOS testing needs macOS with Xcode and a working simctl command. Select the "
                                "full Xcode installation with xcode-select.")
            elif "Booted" not in booted.stdout and not c.udid:
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
    title: str = ""
    steps: list[IosStep] = Field(default_factory=list, max_length=60)
    not_possible: str = ""
    from_launch: bool = False  # (start from a fresh launch of the app: its steps first walk the path to a screen)


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
        if plan.title:
            record["title"] = plan.title
        if self.bundle_id:
            try:
                if plan.from_launch:
                    self.d.terminate_app(self.bundle_id)
                self.d.activate_app(self.bundle_id)
            except Exception:
                pass
        failed, checks, typed = "", 0, []
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
                        typed.append(step.value)
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
        shot = self.run_dir / "screenshots" / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', plan.case)}.png"
        try:
            shown = self.d.page_source if typed else ""
            if any(v and v in (shown or "") for v in typed):  # (like Android: no picture while typed text is shown)
                record["evidence_note"] = "no screenshot: a field still shows a value the test typed"
            else:
                shot.parent.mkdir(exist_ok=True)
                self.d.get_screenshot_as_file(str(shot))
                record["evidence"].append(f"screenshots/{shot.name}")
                live_frame(self.d, self.run_dir)
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


def _screens_brief(screens: list[dict]) -> list[dict]:
    return [{"screen": sc["id"], "reach_by_tapping_from_launch": [t["target"] for t in sc["path"]],
             "controls": [{k: c[k] for k in ("type", "name", "label", "value")} for c in sc["controls"][:60]],
             **({"webview": {k: sc["webview"].get(k) for k in ("title", "ids", "headings")}}
                if (sc.get("webview") or {}).get("inspectable") else {})} for sc in screens]


def _names(controls: list[dict]) -> set[str]:
    return {x for c in controls for x in (c["name"], c["label"]) if x}


def plan_cases(cases: list[dict], controls: list[dict], ask=None, screens: list[dict] | None = None) -> list[IosCase]:
    """The AI turns each test case into steps over the REAL controls of the app (only names / labels a screen
    shows). With `screens` (what discovery found) a case may start from launch and walk to the screen it needs."""
    from .llm import LLMError, ask_structured
    ask = ask or ask_structured
    where = ("SCREENS (each: the controls it shows and the taps that reach it from launch; a WebView's element ids "
             "can be checked with by=css '#id'):\n" + json.dumps(_screens_brief(screens))[:30000]
             if screens else "CONTROLS:\n" + json.dumps(controls[:120]))
    prompt = ("Turn each test case into iOS app steps using ONLY the controls below (find them by accessibility_id "
              "= name, or label; css only inside a WebView). Steps start from a fresh launch of the app: first tap "
              "the path to the screen the case needs. Actions: tap, type (value), clear, assert_visible, "
              "assert_not_visible, assert_text (value), swipe (value up/down/left/right), back. Every case ends with "
              "assertions of its expected result. When no screen has a control for a case, give no steps and say "
              "why in not_possible. Return a JSON array of {case, steps, not_possible}.\n" + where
              + "\nTEST CASES:\n"
              + json.dumps([{"id": c["id"], "title": c.get("title"), "steps": c.get("steps")} for c in cases]))
    try:
        plans = ask(prompt, list[IosCase] | IosCase, agent="ios", page="screen")
    except (LLMError, ValueError) as error:
        return [IosCase(case=c["id"], not_possible=f"the AI could not plan iOS steps ({str(error)[:120]})")
                for c in cases]
    plans = plans if isinstance(plans, list) else [plans]
    known = {c["id"] for c in cases}
    names = _names(controls) | {n for sc in screens or [] for n in _names(sc["controls"])}
    css = {f"#{i}" for sc in screens or [] for i in ((sc.get("webview") or {}).get("ids") or [])}
    out = []
    for p in plans:
        if p.case not in known:
            continue
        invented = [s.target for s in p.steps if s.target and (
            (s.by in ("accessibility_id", "label", "name") and s.target not in names)
            or (s.by == "css" and screens is not None and s.target not in css))]
        title = next((c.get("title") or "" for c in cases if c["id"] == p.case), "")
        out.append(p.model_copy(update={"from_launch": bool(screens), "title": p.title or title}) if not invented
                   else IosCase(case=p.case, title=title, not_possible=f"the plan used controls the app does not "
                                                                       f"show: {invented[:3]}"))
    return out + [IosCase(case=c["id"], title=c.get("title") or "", not_possible="the AI gave no iOS steps for it")
                  for c in cases if c["id"] not in {p.case for p in out}]


# ---------------------------------------------------------------- autonomous: discover, inspect, design, run

TAPPABLE = {"Button", "Cell", "Link", "Tab"}
# never tapped while exploring (an autonomous run changes nothing): money, accounts, data, messages, permissions
RISKY = re.compile(r"delete|remove|erase|reset|pay|buy|purchase|order|checkout|subscribe|log ?out|sign ?out|"
                   r"submit|send|confirm|call|share|allow|deny|unsubscribe|cancel (my )?account", re.I)


def live_frame(driver, run_dir: Path) -> None:
    """The device's current screen as the run's live frame (live/device.jpg: Live Execution shows it)."""
    try:
        data = driver.get_screenshot_as_png()
        folder = Path(run_dir) / "live"
        folder.mkdir(exist_ok=True)
        tmp = folder / "device.tmp"
        tmp.write_bytes(data)
        tmp.replace(folder / "device.jpg")  # (the frame endpoint sends PNG data with its real type)
    except Exception:
        pass


def _key(control: dict) -> dict:
    return ({"by": "accessibility_id", "target": control["name"]} if control["name"]
            else {"by": "label", "target": control["label"]})


def _signature(controls: list[dict]) -> frozenset:
    return frozenset((c["type"], c["name"] or c["label"]) for c in controls if c["type"] != "StaticText"
                     or c["name"]) or frozenset((c["type"], c["label"]) for c in controls)


def webview_snapshot(driver, switches: list[dict] | None = None) -> dict:
    """The app's WebView on this screen: inspectable (its title, element ids, headings) or exactly why not."""
    has_view = "XCUIElementTypeWebView" in (getattr(driver, "page_source", "") or "")
    contexts = [str(c) for c in (getattr(driver, "contexts", None) or [])]
    webviews = [c for c in contexts if c.startswith("WEBVIEW")]
    if not webviews:
        return ({"inspectable": False, "why": "the screen shows a WebView, but no WebView context is offered: the "
                 "test build's WKWebView must set isInspectable = true (iOS 16.4+)"} if has_view else {})
    try:
        driver.switch_to.context(webviews[-1])
        (switches if switches is not None else []).append({"to": webviews[-1], "because": "inspect the WebView"})
        info = {"inspectable": True, "context": webviews[-1],
                "title": str(driver.execute_script("return document.title") or "")[:200],
                "ids": [str(i) for i in (driver.execute_script(
                    "return [...document.querySelectorAll('[id]')].filter(e => e.offsetParent !== null)"
                    ".slice(0, 40).map(e => e.id)") or []) if re.fullmatch(r"[A-Za-z][\w-]{0,60}", str(i))],
                "headings": [str(t)[:120] for t in (driver.execute_script(
                    "return [...document.querySelectorAll('h1,h2,h3')].slice(0, 10).map(e => e.innerText.trim())")
                    or []) if str(t).strip()]}
    except Exception as error:
        info = {"inspectable": False, "why": f"the WebView could not be read: {type(error).__name__}"}
    finally:
        try:
            driver.switch_to.context("NATIVE_APP")
            (switches if switches is not None else []).append({"to": "NATIVE_APP", "because": "back to native UI"})
        except Exception:
            pass
    return info


def explore(driver, run_dir: Path, bundle_id: str, *, max_screens: int = 12, max_taps: int = 40,
            say=lambda line: None, settle_s: float = 1.0) -> dict:
    """Discover the app: from a fresh launch, tap each safe control of each screen found (breadth first, bounded),
    replaying the path from launch each time. Records every screen (its controls, its WebView, a screenshot) and
    every transition. Nothing risky is tapped (RISKY) and nothing is typed."""
    from appium.webdriver.common.appiumby import AppiumBy
    run_dir = Path(run_dir)
    (run_dir / "screens").mkdir(parents=True, exist_ok=True)
    switches: list[dict] = []

    def restart():
        try:
            driver.terminate_app(bundle_id)
        except Exception:
            pass
        driver.activate_app(bundle_id)
        time.sleep(settle_s)

    def tap(k: dict) -> bool:
        how = ((AppiumBy.ACCESSIBILITY_ID, k["target"]) if k["by"] == "accessibility_id"
               else (AppiumBy.IOS_PREDICATE, f"label == {json.dumps(k['target'])}"))
        found = [e for e in driver.find_elements(*how) if e.is_displayed()]
        if len(found) != 1:
            return False
        found[0].click()
        time.sleep(settle_s)
        return True

    def read() -> tuple[list[dict], dict]:
        return screen(driver.page_source), webview_snapshot(driver, switches)

    screens, transitions, skipped, seen = [], [], [], {}

    def add(controls, web, path):
        sid = f"S{len(screens) + 1}"
        seen[_signature(controls)] = sid
        shot = run_dir / "screens" / f"{sid}.png"
        try:
            driver.get_screenshot_as_file(str(shot))
        except Exception:
            pass
        live_frame(driver, run_dir)
        screens.append({"id": sid, "path": path, "controls": controls, "webview": web,
                        "screenshot": f"screens/{sid}.png" if shot.is_file() else ""})
        say(f"[ios] screen {sid}: {len(controls)} control(s)"
            + (f", WebView '{web.get('title', '')}'" if web.get("inspectable") else
               ", WebView not inspectable" if web else "") + (f" (via {' > '.join(t['target'] for t in path)})"
                                                               if path else " (launch screen)"))
        return sid

    restart()
    add(*read(), [])
    queue, taps = ["S1"], 0
    while queue and taps < max_taps and len(screens) < max_screens:
        current = queue.pop(0)
        here = next(sc for sc in screens if sc["id"] == current)
        for c in [c for c in here["controls"] if c["type"] in TAPPABLE and c["enabled"]]:
            label = " ".join([c["name"], c["label"]])
            if RISKY.search(label):
                skipped.append({"screen": here["id"], "control": c["name"] or c["label"], "why": "could change data"})
                continue
            if taps >= max_taps or len(screens) >= max_screens:
                break
            restart()
            if not all(tap(k) for k in here["path"]):
                skipped.append({"screen": here["id"], "control": label.strip(), "why": "its path could not be replayed"})
                continue
            if not tap(_key(c)):
                skipped.append({"screen": here["id"], "control": label.strip(), "why": "not one visible control"})
                continue
            taps += 1
            controls, web = read()
            sig = _signature(controls)
            to = seen.get(sig)
            if not to:
                to = add(controls, web, here["path"] + [_key(c)])
                queue.append(to)
            transitions.append({"from": here["id"], "tap": _key(c), "to": to})
    model = {"screens": screens, "transitions": transitions, "skipped": skipped, "taps": taps,
             "context_switches": switches}
    (run_dir / "ios_screens.json").write_text(json.dumps(model, indent=1), encoding="utf-8")
    return model


def _distinct(target: dict, source: dict | None) -> dict | None:
    """A named control the target screen shows and the source screen does not (proves the move)."""
    before = _names(source["controls"]) if source else set()
    for kind in ("NavigationBar", "StaticText", "Button", "Cell", "TextField", "Image", "Other"):
        for c in target["controls"]:
            if c["type"] == kind and c["name"] and c["name"] not in before:
                return c
    return None


def autonomous_cases(model: dict) -> list[IosCase]:
    """Scenarios from what discovery really saw (no AI needed): each navigation (tap -> a new screen, checked by a
    control only that screen shows, then back to launch works), and each WebView (its web content is shown and the
    native screen is usable again - the context goes there and back). A WebView that cannot be inspected is a
    'Not automated' case with the exact reason."""
    by_id = {sc["id"]: sc for sc in model["screens"]}
    out, n = [], 0

    def case(title, steps=None, why=""):
        nonlocal n
        n += 1
        out.append(IosCase(case=f"IOS-AUTO-{n}", title=title, steps=steps or [], not_possible=why, from_launch=True))

    walked = set()
    for t in model["transitions"]:
        src, dst = by_id[t["from"]], by_id[t["to"]]
        if t["to"] == t["from"] or t["to"] in walked:
            continue
        mark = _distinct(dst, src)
        if not mark:
            continue
        walked.add(t["to"])
        path = [IosStep(action="tap", **k) for k in src["path"]]
        case(f"Tapping '{t['tap']['target']}' on {src['id']} opens {dst['id']}, which shows '{mark['name']}'",
             path + [IosStep(action="tap", **t["tap"]),
                     IosStep(action="assert_visible", by="accessibility_id", target=mark["name"])])
    for sc in model["screens"]:
        web = sc.get("webview") or {}
        if not web:
            continue
        if not web.get("inspectable"):
            case(f"The web content of {sc['id']} is shown", why=web.get("why", "the WebView cannot be inspected"))
            continue
        native = next((c for c in sc["controls"] if c["name"] and c["type"] != "WebView"), None)
        if not web.get("ids") or not native:
            continue
        path = [IosStep(action="tap", **k) for k in sc["path"]]
        case(f"{sc['id']} shows its web content (#{web['ids'][0]}) and its native '{native['name']}' stays usable",
             path + [IosStep(action="assert_visible", by="css", target=f"#{web['ids'][0]}"),
                     IosStep(action="assert_visible", by="accessibility_id", target=native["name"])])
    return out


def ai_scenarios(model: dict, ask=None, limit: int = 8) -> list[IosCase]:
    """Scenarios the AI designs over the discovered screens (validated like plan_cases: only real controls).
    [] when no AI is available - the rule-based scenarios still run."""
    from .llm import LLMError, ask_structured
    ask = ask or ask_structured
    prompt = ("You test an iOS app. From these discovered screens, design up to " + str(limit) + " meaningful test scenarios a QA "
              "tester would run (navigation, content, form validation with clearly fake data, WebView content). "
              "Never pay, order, delete, send, log out or change settings. Each starts from a fresh launch: tap the "
              "path to its screen first, then act, then assert. Use ONLY controls listed (accessibility_id = name, "
              "or label; css '#id' only for WebView ids). Actions: tap, type, clear, assert_visible, "
              "assert_not_visible, assert_text, swipe, back. Return a JSON array of {case, title, steps} with case "
              "ids IOS-AI-1, IOS-AI-2 ...\nSCREENS:\n") + json.dumps(_screens_brief(model["screens"]))[:30000]
    try:
        plans = ask(prompt, list[IosCase] | IosCase, agent="ios", page="explore")
    except (LLMError, ValueError):
        return []
    plans = plans if isinstance(plans, list) else [plans]
    names = {n for sc in model["screens"] for n in _names(sc["controls"])}
    css = {f"#{i}" for sc in model["screens"] for i in ((sc.get("webview") or {}).get("ids") or [])}
    out = []
    for i, p in enumerate(plans[:limit], 1):
        bad = [s.target for s in p.steps if s.target and ((s.by == "css" and s.target not in css) or (
            s.by in ("accessibility_id", "label", "name") and s.target not in names))]
        risky = [s.target for s in p.steps if s.action == "tap" and RISKY.search(s.target)]
        checks = [s for s in p.steps if s.action.startswith("assert")]
        cid = f"IOS-AI-{i}"
        if bad or risky or not checks:
            out.append(IosCase(case=cid, title=p.title, not_possible=(
                f"it would tap something that changes data: {risky[:2]}" if risky else
                f"the AI used controls the app does not show: {bad[:3]}" if bad else "it checked nothing")))
        else:
            out.append(p.model_copy(update={"case": cid, "from_launch": True}))
    return out
