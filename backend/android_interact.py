"""User-like testing in test mode: a TEST BUILD of an Android app, or a test / demo WEBSITE in Android Chrome.

Safe discovery only looks and navigates. When the person ticks the test-mode box (config interaction_testing),
this module also acts like a manual tester:
  * exercises each discovered, labelled interactive control except the actions test mode never uses
  * tries forms with empty, invalid and valid data, signs up with generated test data, and logs in with the supplied
    test account (or the account it just registered)
  * checks that a screen survives rotation, leaving and resuming the app, and the system Back button (native apps)
  * (with AI) drafts end-to-end user journeys from what it saw
The website explorer (android_site.SiteSession) builds on this core: every menu first, every page to its end, then
each feature.

Every check becomes an approved QA-contract flow, run by the same trusted runtime as hand-written flows
(qa_runtime.ContractRuntime). Each starts from a fresh state (cleared app data / this website's cookies and storage),
and each is REPLAYED once before it is kept:
  observed   behaviour seen during exploration (regression). Not repeatable on replay -> dropped, never a flaky test.
  universal  what any tester expects (a wrong password is refused, the screen survives rotation). Kept even when it
             fails twice: a consistent failure is a finding, reported as a failed test.
Everything except checkout: checkout / payment / placing an order, paid subscriptions, deleting an account, crash
buttons, sharing / sending to other apps, calls and SMS are never pressed (qa_contracts.never_in_test_mode).
Every planned check ends in the coverage list as passed, failed or not tested with a plain reason - no silent gaps.
"""

import re
import secrets
import time
from collections import Counter

from .android import AndroidEnvironmentError
from .qa_contracts import TEST_MODE_NEVER, TEST_MODE_NEVER_NATIVE, Flow, never_in_test_mode, parse_contract
from .safety import redact

# The actions test mode never uses (never_in_test_mode also gives the plain reason the report shows).
NEVER_TAP = re.compile("|".join(pattern.pattern for _, pattern in TEST_MODE_NEVER)
                       + "|" + TEST_MODE_NEVER_NATIVE[1].pattern, re.I)
SUBMIT = re.compile(r"\b(log ?in|sign ?in|submit|continue|next|search|go|done|ok|apply|sign ?up|register|create account|"
                    r"send|save|subscribe)\b", re.I)
PAYMENT_INPUTS = {"card_number", "card_expiry", "cvv"}
LOGIN = re.compile(r"\b(log ?in|sign ?in)\b", re.I)
SEARCH = re.compile(r"\bsearch\b", re.I)
SIGNUP = re.compile(r"\b(sign ?up|register|registration|create (?:an |my )?account)\b", re.I)
VOLATILE = re.compile(r"\b\d{1,2}:\d{2}\b|\b(ago|today|yesterday|now|seconds?|minutes?)\b|\d{4}-\d{2}-\d{2}", re.I)
SUCCESS = re.compile(r"\b(success\w*|welcome|created|registered|verify|check your email|saved|updated|applied|"
                     r"submitted|complete\w*|sent|thank(?:s| you)|subscribed|signing up|added)\b", re.I)

WRONG_PASSWORD = "BLOWAI_SECRET_AUTO_WRONG_PASSWORD"  # noqa: S105 - reference names, not credentials
STRONG_PASSWORD = "BLOWAI_SECRET_AUTO_STRONG_PASSWORD"  # noqa: S105
TEST_USERNAME = "BLOWAI_SECRET_TEST_USERNAME"
TEST_PASSWORD = "BLOWAI_SECRET_TEST_PASSWORD"  # noqa: S105
SIGNUP_EMAIL = "BLOWAI_SECRET_AUTO_SIGNUP_EMAIL"
SIGNUP_USERNAME = "BLOWAI_SECRET_AUTO_SIGNUP_USERNAME"
# The account test mode registered itself (when no test account was given): kept privately for the final run.
ACCOUNT_USERNAME = "BLOWAI_SECRET_AUTO_ACCOUNT_USERNAME"
ACCOUNT_PASSWORD = "BLOWAI_SECRET_AUTO_ACCOUNT_PASSWORD"  # noqa: S105
GENERATED_SECRETS = (WRONG_PASSWORD, STRONG_PASSWORD, SIGNUP_EMAIL, SIGNUP_USERNAME)


def _new_signup_email() -> str:
    return "qa" + secrets.token_hex(4) + "@example.com"


def _new_signup_username() -> str:
    return "qa" + secrets.token_hex(4)


def generated_secrets() -> dict:
    """Throwaway values, new for every run: a password nobody has, and a strong one for invalid-format probes."""
    return {WRONG_PASSWORD: "Wrong-" + secrets.token_hex(5) + "!",
            STRONG_PASSWORD: "Qa-" + secrets.token_hex(5) + "#9x",
            SIGNUP_EMAIL: _new_signup_email(),
            SIGNUP_USERNAME: _new_signup_username()}


def flow_secrets(environment: dict, saved: dict | None = None) -> dict:
    """Secrets the auto flows may use: generated throwaways, the account test mode registered (saved privately
    during exploration), and the person's private test account, if given."""
    values = generated_secrets()
    for name, value in (saved or {}).items():
        if name.startswith("BLOWAI_SECRET_AUTO_") and isinstance(value, str) and value:
            values[name] = value
    for name in (TEST_USERNAME, TEST_PASSWORD):
        if environment.get(name):
            values[name] = environment[name]
    return values


# ------------------------------------------------------------------ element helpers

def label(element: dict) -> str:
    resource = (element.get("resource_id") or "").rsplit("/", 1)[-1]
    # Each part once: a web box's label arrives as both accessibility_id and hint, and "Message: message-text Message:"
    # would read as "text message" (an SMS, never used) - demoblaze's contact box, run android_20261110_113902_88059d.
    parts = dict.fromkeys(x for x in (element.get("text"), element.get("accessibility_id"), resource, element.get("hint")) if x)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", " ".join(parts)).replace("_", " ").strip()


def name(element: dict) -> str:
    return (element.get("text") or element.get("accessibility_id") or element.get("hint")
            or (element.get("resource_id") or "").rsplit("/", 1)[-1] or "control")[:80]


def usable(element: dict) -> bool:
    return bool(element.get("visible") and element.get("enabled", True) and element.get("locators")
                and element.get("locator_unique", True) and not element.get("within_webview")
                and not element.get("outside_active_drawer"))


def _top(element: dict) -> int:
    match = re.match(r"\[(-?\d+),(-?\d+)\]", element.get("bounds") or "")
    return int(match.group(2)) if match else 10 ** 6


def _swipe(direction: str) -> str:
    """Discovery records scrollGesture directions; flows swipe (finger up = content moves down)."""
    return {"down": "up", "up": "down"}.get(direction or "down", "up")


def reach(element: dict) -> list[dict]:
    """The steps a user takes to bring a control below the screen edge into view before using it."""
    if element.get("web_below_fold"):
        return [{"action": "scroll_to", "locator": {"strategy": "css", "value": "html"},
                 "target": element["locators"][0], "value": "up"}]
    hint = element.get("scroll_hint") or {}
    if element.get("requires_scroll") and hint.get("container"):
        return [{"action": "scroll_to", "locator": hint["container"], "target": element["locators"][0],
                 "value": _swipe(hint.get("direction"))}]
    return []


def tap(element: dict) -> dict:
    # "test_form" marks a deliberate user action; the runtime refuses login/submit/add taps marked as navigation.
    return {"action": "tap", "locator": element["locators"][0], "purpose": "test_form"}


def fill(element: dict, value: str | None = None, secret_ref: str | None = None) -> dict:
    step = {"action": "fill", "locator": element["locators"][0]}
    if secret_ref:
        step.update(secret_ref=secret_ref, sensitive=bool(element.get("password")) or secret_ref != TEST_USERNAME)
    else:
        step["value"] = value
    return step


def path_steps(screens: list[dict], screen: dict) -> list[dict]:
    """The recorded discovery path from the launch screen to this screen, as flow steps."""
    elements = {e["id"]: e for s in screens for e in s["elements"]}
    # Authenticated screens are discovered after a successful private login.
    # Carry that replayable setup into each generated journey without copying
    # credential values (the setup contains secret references only).
    steps = list(screen.get("authentication_setup_steps", []))
    for element_id in screen.get("path", []):
        element = elements[element_id]
        steps += reach(element) + [tap(element)]
    return steps


def anchor(screen: dict, common: set = frozenset()) -> dict | None:
    """A stable control that identifies the screen: labelled, near the top, outside scrolling lists, and not one of
    the `common` controls every screen shows (a menu button proves nothing about which screen is open)."""
    candidates = [e for e in screen["elements"] if usable(e) and not e.get("input_capable")
                  and not e.get("requires_scroll") and family(e) not in common
                  and (e.get("text") or e.get("accessibility_id")) and not VOLATILE.search(e.get("text") or "")]
    # Prefer the actual page heading. A shared toolbar button (for example,
    # "View menu") proves the app is open, but does not prove Back/resume returned
    # to the same screen.
    heading = screen.get("screen_name", "").strip().casefold()
    heading_candidates = [e for e in candidates if e.get("text", "").strip().casefold() == heading]
    if heading_candidates:
        candidates = heading_candidates
    candidates.sort(key=lambda e: (bool(e.get("scroll_hint")), not (e.get("resource_id") or e.get("accessibility_id")),
                                   _top(e)))
    return candidates[0] if candidates else None


def anchor_checks(element: dict) -> list[dict]:
    steps = [{"action": "assert_visible", "locator": element["locators"][0]}]
    if element.get("text") and element.get("text_comparable", True) and element["locators"][0]["strategy"] != "text":
        steps.append({"action": "assert_text", "locator": element["locators"][0], "value": element["text"]})
    return steps


def present(screen: dict, element: dict) -> bool:
    """The same control (same identity) is shown on this live screen."""
    for candidate in screen.get("elements", []):
        if not candidate.get("visible") or candidate.get("class_name") != element.get("class_name"):
            continue
        if any(element.get(k) and element[k] == candidate.get(k) for k in ("resource_id", "accessibility_id")):
            return True
        if element["locators"][0] in candidate.get("locators", []):
            return True
    return False


# ------------------------------------------------------------------ what to try

def family(element: dict) -> tuple:
    locator = (element.get("locators") or [{}])[0]
    return (element.get("class_name"), element.get("accessibility_id") or element.get("resource_id") or element.get("text"),
            locator.get("strategy"), locator.get("value"))


def reversible_candidates(screen: dict, native: bool = True) -> list[dict]:
    out = []
    form = find_form(screen, native)
    submit_id = form["submit"]["id"] if form else None
    for element in screen.get("elements", []):
        if not usable(element) or element.get("input_capable"):
            continue
        if not (element.get("clickable") or element.get("checkable")):
            continue
        if element.get("id") == submit_id:
            continue  # form-specific probes already test the submit action with deliberate data
        words = label(element)
        if not words or never_in_test_mode(words, native):
            continue
        # In test mode, exercise every labelled, uniquely located control unless test mode never uses it.
        # Discovery alone only navigates; this is where buttons such as Add To Cart and review actions get an
        # action plus a visible-result assertion.
        out.append(element)
    return out


def find_form(screen: dict, native: bool = True) -> dict | None:
    inputs = [e for e in screen.get("elements", []) if usable(e) and e.get("input_capable")]
    if not inputs:
        return None
    if any(field_kind(element) in PAYMENT_INPUTS for element in inputs):
        return None  # payment flows are excluded even when their submit button has a generic label
    buttons = [e for e in screen.get("elements", [])
               if usable(e) and e.get("clickable") and not e.get("input_capable")
               and e.get("navigation_role") not in ("tab", "menu_item")
               and SUBMIT.search(label(e)) and not never_in_test_mode(label(e), native)]
    return build_form(inputs, buttons)


def build_form(inputs: list[dict], buttons: list[dict]) -> dict | None:
    """What kind of form these boxes and buttons make (login, search, sign-up or another form), and its submit."""
    if not inputs or not buttons:
        return None
    password = next((e for e in inputs if e.get("password")), None)
    if password and any(LOGIN.search(label(b)) for b in buttons):
        kind = "login"
        submit = next(b for b in buttons if LOGIN.search(label(b)))
    elif any(SEARCH.search(label(e)) for e in [*inputs, *buttons]):
        kind = "search"
        submit = next((b for b in buttons if SEARCH.search(label(b))), buttons[0])
    else:
        signup = next((b for b in buttons if SIGNUP.search(label(b))), None)
        kind = "signup" if signup else "form"
        submit = signup or buttons[0]
    username = next((e for e in inputs if not e.get("password")), None)
    return {"kind": kind, "inputs": inputs, "password": password, "username": username, "submit": submit}


def field_kind(element: dict) -> str:
    from .testdata import field_kind as kind_of
    box_type = "password" if element.get("password") else element.get("input_type") or ""
    return kind_of({"label": label(element), "type": box_type, "autocomplete": element.get("autocomplete") or ""}) or "text"


# ------------------------------------------------------------------ what changed

def _keyed(screen: dict) -> dict:
    groups = {}
    for element in screen.get("elements", []):
        if (not element.get("visible") or element.get("within_webview") or element.get("input_capable")
                or element.get("outside_active_drawer") or not (element.get("resource_id") or element.get("accessibility_id"))):
            continue
        key = (element.get("class_name"), element.get("resource_id") or "", element.get("accessibility_id") or "")
        groups.setdefault(key, []).append(element)
    return {key: items[0] for key, items in groups.items() if len(items) == 1}


def screen_diff(before: dict, after: dict) -> list[dict]:
    """What visibly changed after one user action, using only stable identities (never input contents)."""
    changes = []
    old, new = _keyed(before), _keyed(after)
    for key, element in new.items():
        previous = old.get(key)
        text = element.get("text") or ""
        if previous is None:
            if usable(element) and (text or element.get("accessibility_id")) and not VOLATILE.search(text):
                changes.append({"kind": "appeared", "element": element})
        elif text != (previous.get("text") or "") and text and element.get("text_comparable", True) and not VOLATILE.search(text):
            changes.append({"kind": "text", "element": element, "before": previous.get("text") or "", "after": text})
        elif element.get("checkable") and element.get("checked") != previous.get("checked"):
            changes.append({"kind": "checked", "element": element, "after": bool(element.get("checked"))})
    for key, element in old.items():
        if key not in new and usable(element):
            changes.append({"kind": "disappeared", "element": element})
    # A list sorted again: the first item of a repeated kind (the first product title) shows another text.
    def firsts(screen):
        out = {}
        for element in screen.get("elements", []):
            key = (element.get("class_name"), element.get("resource_id") or "")
            if element.get("visible") and element.get("resource_id") and element.get("text") and key not in out:
                out[key] = element
        return out
    old_first, new_first = firsts(before), firsts(after)
    repeated = {key for key, count in Counter((e.get("class_name"), e.get("resource_id") or "")
                                              for e in after.get("elements", []) if e.get("visible")).items() if count > 1}
    for key in [k for k in new_first if k in repeated]:  # in screen order, so the titles are stable
        if key in old_first and key in new_first and old_first[key]["text"] != new_first[key]["text"] \
                and not VOLATILE.search(new_first[key]["text"]):
            element = {**new_first[key], "accessibility_id": "", "locators": [
                {"strategy": "xpath", "value": f'(//*[@resource-id="{key[1]}"])[1]'}]}
            changes.append({"kind": "text", "element": element, "before": old_first[key]["text"],
                            "after": new_first[key]["text"]})
    # Messages (validation errors, "added", "empty") often have no id: new, uniquely located texts.
    seen = Counter(e.get("text") for e in before.get("elements", []) if e.get("visible") and e.get("text"))
    for element in after.get("elements", []):
        text = element.get("text") or ""
        if (element.get("type") == "text" and text and not seen[text] and usable(element)
                and not (element.get("resource_id") or element.get("accessibility_id"))
                and element.get("text_comparable", True) and not VOLATILE.search(text)
                and element["locators"][0]["strategy"] == "text"):
            changes.append({"kind": "message", "element": element})
    return changes


def assertion_steps(changes: list[dict], limit: int = 3) -> list[dict]:
    """Assertions for what changed. A browser message (alert) comes first: it is shown right after the action and
    must be checked (and closed) before anything else on the page can be read."""
    order = {"alert": -1, "title": 0, "text": 0, "checked": 1, "appeared": 2, "message": 3, "disappeared": 4}
    # A short-lived message ("Added to cart") is a weak, timing-dependent check: use it only when nothing lasting changed.
    lasting = [c for c in changes if c["kind"] in ("text", "checked", "appeared", "title")]
    if lasting:
        changes = [c for c in changes if c["kind"] == "alert"] + lasting + [c for c in changes if c["kind"] == "disappeared"]
    steps = []
    for change in sorted(changes, key=lambda c: order[c["kind"]]):
        if change["kind"] == "alert":
            steps.append({"action": "assert_alert", "value": change["text"]})
            continue
        if change["kind"] == "title":
            steps.append({"action": "assert_screen", "value": change["after"]})
            if len([s for s in steps if s["action"] != "assert_alert"]) >= limit:
                break
            continue
        element = change["element"]
        locator = element["locators"][0]
        if change["kind"] == "text":
            steps.append({"action": "assert_text", "locator": locator, "value": change["after"]})
        elif change["kind"] in ("message", "appeared"):
            text = element.get("text") or ""
            if text and element.get("text_comparable", True) and locator["strategy"] != "text":
                steps.append({"action": "assert_text", "locator": locator, "value": text})
            else:
                steps.append({"action": "assert_visible", "locator": locator})
        elif change["kind"] == "checked":
            steps.append({"action": "assert_checked", "locator": locator, "value": "true" if change["after"] else "false"})
        else:
            steps.append({"action": "assert_not_visible", "locator": locator})
        if len([s for s in steps if s["action"] != "assert_alert"]) >= limit:
            break
    return steps


def describe(changes: list[dict]) -> str:
    parts = []
    for change in changes[:2]:
        if change["kind"] == "alert":
            parts.append(f"the message '{change['text'][:50]}' appears")
            continue
        if change["kind"] == "title":
            parts.append(f"'{change['after'][:50]}' opens")
            continue
        element = change["element"]
        if change["kind"] == "text" and change.get("before") and not (element.get("resource_id")
                                                                       or element.get("accessibility_id")):
            # a text without a name of its own (a cart count): say what it was and what it became
            parts.append(f"'{change['before'][:40]}' changes to '{change['after'][:40]}'")
        elif change["kind"] == "text" and change.get("before"):
            subject = element.get("accessibility_id") or (element.get("resource_id") or "").rsplit("/", 1)[-1]
            parts.append(f"'{subject[:40]}' changes from '{change['before'][:40]}' to '{change['after'][:40]}'")
        elif change["kind"] == "text":
            parts.append(f"'{name(element)[:40]}' changes to '{change['after'][:40]}'")
        elif change["kind"] in ("message", "appeared"):
            parts.append(f"'{name(element)[:50]}' appears")
        elif change["kind"] == "checked":
            parts.append(f"'{name(element)[:40]}' turns {'on' if change['after'] else 'off'}")
        else:
            parts.append(f"'{name(element)[:40]}' disappears")
    return ", ".join(parts) or "the screen changes"


# ------------------------------------------------------------------ the coverage list (plain reasons)

PLAIN = {
    "not repeatable": "the result was different when the check was repeated from a fresh start, so it is not kept "
                      "as a test",
    "inconclusive": "the check could not be completed (a control could not be found or used)",
    "no visible change": "using it changed nothing visible, so there is nothing to check",
    "opens another app": "it opens another app or website, which is not followed",
    "could not be tried": "the check could not be run",
    "not testable": "no valid test could be made from what was seen",
    "rejected": "the AI's suggestion was not safe or not valid",
    "not attempted": "it could not be reached",
    "AI not used": "the AI did not give a usable answer; the rule-based checks stand",
    "protected by a CAPTCHA": "the form is protected by a CAPTCHA, which only a person may complete; Qpilot never "
                              "solves CAPTCHAs",
}


def budget_reason(reason: str) -> str:
    """Why a planned check never ran, in plain words."""
    text = str(reason)
    if "time limit" in text.casefold():
        return "not reached within the time limit for user-like testing"
    if "test limit" in text.casefold():
        return "not reached: the limit of user-like tries was used up"
    if "stop" in text.casefold():
        return "not tested: the run was stopped"
    if "bot check" in text.casefold() or "blocks automated visitors" in text.casefold():
        return "behind a bot check nobody completed"
    return "not tested: " + text[:160]


# ------------------------------------------------------------------ the session

class Budget(Exception):
    """The interaction budget (tries or time) is used up, or the person pressed Stop."""


class Session:
    """Runs inside discovery with the discovery driver. `device` gives:
    driver, config, screens, stop_path, deadline, max_tries, fresh_start() -> live launch screen,
    go_to(screen) -> live screen (from cleared data), observe() -> live settled screen."""

    def __init__(self, device, environment=None):
        self.device = device
        self.screens = device.screens
        self.web = (getattr(device, "config", None) or {}).get("app_mode") == "web"
        self.native = not self.web
        self.secrets = flow_secrets(environment or {})
        self.account = (TEST_USERNAME, TEST_PASSWORD) if TEST_USERNAME in self.secrets and TEST_PASSWORD in self.secrets else None
        self.given_account = self.account is not None
        self.flows, self.tried, self.findings, self.coverage = [], [], [], []
        self._covered = set()
        self.used = 0
        self.check_count = 0
        self.built = 0
        self.seen = set()
        self.reserve = 0
        self.base = {"version": 1, "test_environment": True, "test_mode": True, "flows": []}
        if self.web:
            from .qa_contracts import origin
            self.base["allowed_origins"] = [origin(device.config["start_url"])]
        else:
            self.base["android_package"] = self.screens[0]["package_name"]

    @property
    def has_account(self) -> bool:
        return self.account is not None

    def protected(self, words: str, navigation: bool = False) -> str:
        """Why test mode never presses this ('' = it may). `navigation`: a menu item that only opens an in-app
        screen (QR Code Scanner) - its device feature is never used, the screen may open."""
        return never_in_test_mode(words, self.native and not navigation)

    def nav(self, screen: dict) -> list[dict]:
        """Flow steps that open this screen from the fresh start."""
        return path_steps(self.screens, screen)

    def diff(self, before: dict, after: dict) -> list[dict]:
        return screen_diff(before, after)

    # -------- budget and execution
    def spend(self):
        if self.device.stop_path.exists():
            raise Budget("Stop requested")
        if self.used >= self.device.max_tries - self.reserve:
            raise Budget("User-like test limit reached")
        if time.monotonic() >= self.device.deadline:
            raise Budget("User-like testing time limit reached")
        self.used += 1

    def _adapter(self, contract):
        from .qa_runtime import AndroidContractAdapter
        config = dict(self.device.config)
        if self.native:
            config["package_name"] = self.base["android_package"]
        return AndroidContractAdapter(self.device.driver, config, contract, stop_path=self.device.stop_path)

    def perform(self, steps: list[dict]):
        """Do the action steps (no assertions) with the trusted adapter: unique visible controls only."""
        from .qa_contracts import Locator
        contract = parse_contract(self.base)
        adapter = self._adapter(contract)
        for step in steps:
            if step["action"] in ("back", "rotate", "background", "hide_keyboard"):
                adapter.device_action(step["action"], step.get("value"))
                continue
            if step["action"] == "open":
                adapter.open(step["value"])
                continue
            if step["action"].startswith("assert_"):
                continue
            element = adapter.find(Locator(**step["locator"]))
            if step["action"] == "scroll_to":
                adapter.scroll_to(element, Locator(**step["target"]), step["value"])
            elif step["action"] == "tap":
                if self.protected(adapter.identity(element), navigation=step.get("purpose") == "navigation"):
                    raise ValueError("Blocked an irreversible live control")
                adapter.tap(element)
            elif step["action"] == "fill":
                adapter.fill(element, self.secrets[step["secret_ref"]] if step.get("secret_ref") else step["value"])
            elif step["action"] == "select":
                adapter.select(element, step["value"])

    def replay(self, flow: dict) -> str:
        """'' when the flow passes from cleared app data, else the reason it did not."""
        from .qa_runtime import ContractRuntime
        signup_refs = {step.get("secret_ref") for step in flow.get("steps", [])}
        if SIGNUP_EMAIL in signup_refs or SIGNUP_USERNAME in signup_refs:
            # Signup creates a server-side account, which clearing local app data
            # cannot undo. Give each replay a unique address so the replay tests
            # the signup path instead of colliding with its discovery attempt.
            self.secrets[SIGNUP_EMAIL] = _new_signup_email()
            self.secrets[SIGNUP_USERNAME] = _new_signup_username()
        contract = parse_contract({**self.base, "flows": [flow]})
        try:
            self.device.fresh_start()
            runtime = ContractRuntime(self._adapter(contract), contract.model_dump(mode="json"),
                                      {"secrets": self.secrets, "databases": {}})
            runtime.execute(flow["id"])
            return ""
        except Budget:
            raise
        except Exception as error:
            from .android_runtime import device_unavailable
            from .android_web import BotCheckBlocked
            if device_unavailable(error) or isinstance(error, BotCheckBlocked):
                raise
            detail = redact(f"{type(error).__name__}: {error}", list(self.secrets.values()))[:240]
            return detail or type(error).__name__

    def build(self, kind: str, title: str, steps: list[dict], authentication=False) -> dict | None:
        self.built += 1
        flow_id = f"auto_{kind}_{self.built:03d}"
        try:
            return Flow.model_validate({"id": flow_id, "title": title[:180], "approved": True,
                                        "authentication": authentication, "steps": steps[:40],
                                        "timeout_s": 120}, context={"test_mode": True}).model_dump(mode="json")
        except ValueError as error:
            self.tried.append({"check": title, "outcome": "not testable", "detail": str(error)[:200]})
            return None

    def keep(self, flow: dict | None, meta: dict, universal: bool = False,
             failures: tuple = ("AssertionError",)) -> bool:
        """Replay the flow from a fresh start before it is kept. A universal check that fails twice with one of the
        `failures` exception types is kept as a finding; any other error (a control that cannot be located) leaves
        it inconclusive."""
        if flow is None:
            return False
        if len(self.flows) >= 100:  # keep the bounded test-build exploration inside the contract limit
            raise Budget("User-like test limit reached")
        self.spend()
        error = self.replay(flow)
        if error and universal:
            self.spend()
            second = self.replay(flow)
            first_assertion = error.split(":", 1)[0] in failures
            second_assertion = second.split(":", 1)[0] in failures
            if first_assertion and second_assertion:
                meta["discovery_replay"] = "failed twice: " + second
                error = ""  # a consistent app assertion failure is a finding; keep it for execution evidence
            else:
                outcome = "not repeatable" if not second else "inconclusive"
                detail = ("The first replay failed, but the retry passed; this behavior was not stable."
                          if not second else "The check could not be verified because a replay hit an automation or locator error.")
                cause = second or error
                self.tried.append({"check": flow["title"], "outcome": outcome,
                                   "detail": redact(detail + " " + cause, list(self.secrets.values()))[:240],
                                   "screen": meta.get("screen")})
                return False
        elif error:
            outcome = "not repeatable" if error.split(":", 1)[0] in ("AssertionError", "ControlMissing") else "inconclusive"
            self.tried.append({"check": flow["title"], "outcome": outcome, "detail": error,
                               "screen": meta.get("screen")})
            return False
        else:
            meta["discovery_replay"] = "passed"
        self.flows.append({"flow": flow, "meta": {**meta, "universal": universal}})
        row = {"check": flow["title"], "outcome": "kept", "detail": meta["discovery_replay"], "screen": meta.get("screen")}
        if meta["discovery_replay"].startswith("failed twice:"):
            row["reason"] = "finding: the check failed on both replays from a fresh start"
        self.tried.append(row)
        return True

    def go_to(self, screen: dict, fresh: bool = True) -> dict:
        """The live screen, opened from a fresh start (`fresh=False`: a website may skip clearing for navigation)."""
        return self.device.go_to(screen)

    def observe_after(self, screen: dict, steps: list[dict], fresh: bool = True, setup: int = 0):
        """Open the screen from cleared data, do the steps, and return (before, after); after is None if the app left.
        Leading scroll steps (and the first `setup` steps: log in, fill the cart) happen before the 'before' picture:
        they are not the action's effect."""
        self.spend()
        before = self.go_to(screen, fresh)
        scrolls = setup
        while scrolls < len(steps) and steps[scrolls]["action"] == "scroll_to":
            scrolls += 1
        try:
            if scrolls:
                self.perform(steps[:scrolls])
                before = self.device.observe()
            self.perform(steps[scrolls:])
            return before, self.device.observe()
        except AndroidEnvironmentError as error:
            if "left the selected" in str(error) or "contract left the" in str(error) or "left the approved" in str(error):
                return before, None  # another app (browser, store, launcher) is in front: never inspected
            raise

    # -------- the coverage list
    def cover(self, area: str, name: str, status: str, reason: str, where: str = "", flow_id: str = "", **extra):
        """One row of 'what was tested': passed / failed / not tested, with a plain reason."""
        entry = {"area": area, "name": redact(str(name), list(self.secrets.values()))[:180], "where": str(where or "")[:120],
                 "status": status, "reason": redact(str(reason or ""), list(self.secrets.values()))[:300]}
        if flow_id:
            entry["flow_id"] = flow_id
        entry.update({k: v for k, v in extra.items() if v})
        self.coverage.append(entry)

    def attempt(self, check, action, *args, area: str = "feature", where: str = ""):
        """One check failing to run (a control gone, a field refusing text) never stops the others."""
        self.check_count += 1
        number = self.check_count
        label = redact(check, list(self.secrets.values()))
        label = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email]", label, flags=re.I)
        label = re.sub(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", "[number]", label)
        label = label[:150]
        before_flows, before_tried = len(self.flows), len(self.tried)
        print(f"[android] Check {number} started: {label}", flush=True)
        try:
            action(*args)
        except Budget as reason:
            print(f"[android] Check {number} stopped when its test budget ended.", flush=True)
            self._cover_attempt(check, area, where, before_flows, before_tried, budget_reason(str(reason)))
            raise
        except Exception as error:
            from .android_runtime import device_unavailable
            from .android_web import BotCheckBlocked
            if device_unavailable(error):
                print(f"[android] Check {number} stopped because the Android session became unavailable.", flush=True)
                raise
            if isinstance(error, BotCheckBlocked):
                self._cover_attempt(check, area, where, before_flows, before_tried, budget_reason(str(error)))
                raise
            self.tried.append({"check": check, "outcome": "could not be tried",
                               "detail": redact(f"{type(error).__name__}: {error}", list(self.secrets.values()))[:240]})
        new_flows = self.flows[before_flows:]
        new_tried = self.tried[before_tried:]
        self._cover_attempt(check, area, where, before_flows, before_tried)
        if new_flows:
            verified = sum(item["meta"].get("discovery_replay") == "passed" for item in new_flows)
            findings = sum(str(item["meta"].get("discovery_replay", "")).startswith("failed twice:")
                           for item in new_flows)
            outcome = f"{verified} replay-verified flow(s)"
            if findings:
                outcome += f", {findings} repeatable assertion failure(s) retained for execution"
        elif new_tried:
            counts = Counter(item.get("outcome", "inconclusive") for item in new_tried)
            outcome = ", ".join(f"{count} {name}" for name, count in sorted(counts.items()))
        else:
            outcome = "no executable result was observed"
        print(f"[android] Check {number} finished: {outcome}.", flush=True)

    def _cover_attempt(self, check, area, where, before_flows, before_tried, stopped: str = ""):
        # A check inside a check (exploring after a login) covers its own rows: never list one twice.
        new_flows = [item for item in self.flows[before_flows:] if id(item) not in self._covered]
        new_tried = [item for item in self.tried[before_tried:] if id(item) not in self._covered]
        self._covered.update(id(item) for item in [*new_flows, *new_tried])
        for item in new_flows:
            replay = str(item["meta"].get("discovery_replay", ""))
            failed = replay.startswith("failed twice:")
            self.cover(area, item["flow"]["title"], "failed" if failed else "passed",
                       replay.removeprefix("failed twice: ") if failed
                       else "worked, and worked again when repeated from a fresh start",
                       where=item["meta"].get("screen") or where, flow_id=item["flow"]["id"])
        for item in new_tried:
            if item.get("outcome") == "kept":
                continue
            reason = item.get("reason") or PLAIN.get(item.get("outcome"), item.get("outcome") or "not tested")
            if item.get("outcome") in ("inconclusive", "could not be tried", "not testable", "rejected") and item.get("detail"):
                reason += ": " + str(item["detail"])[:200]
            # A row may carry its own result (a page read to its end passed; a broken page failed)
            status = item.get("status") or ("failed" if item.get("outcome") == "finding" else "not tested")
            self.cover(area, item.get("check") or check, status, reason, where=item.get("screen") or where,
                       screenshot=item.get("screenshot"), how_to_reach=item.get("how_to_reach"))
        if stopped:
            self.cover(area, check, "not tested", stopped, where=where)
        elif not new_flows and not new_tried:
            self.cover(area, check, "not tested", "no result could be observed", where=where)

    # -------- the checks a tester runs
    def tap_check(self, screen: dict, element: dict):
        key = family(element)
        if key in self.seen:
            return
        self.seen.add(key)
        steps = reach(element) + [tap(element)]
        before, after = self.observe_after(screen, steps)
        what = f"Tap '{name(element)}' on {screen['screen_name']}"
        if after is None:
            self.tried.append({"check": what, "outcome": "opens another app", "detail": "Not followed.", "screen": screen["screen_name"]})
            return
        changes = self.diff(before, after)
        checks = assertion_steps(changes)
        if not checks:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": screen["screen_name"]})
            return
        flow = self.build("action", f"{what}: {describe(changes)}", self.nav(screen) + steps + checks)
        self.keep(flow, {"category": "user_action", "screen_id": screen["id"], "screen": screen["screen_name"],
                         "element_ids": [element["id"]], "expected": f"After tapping '{name(element)}', {describe(changes)} (as observed).",
                         "requirement": "Observed app behaviour on a test build (regression)", "source": "interaction"})

    def form_checks(self, screen: dict, form: dict):
        key = ("form", screen["id"], form["submit"]["id"])
        if key in self.seen:
            return
        self.seen.add(key)
        if form.get("captcha"):
            self.tried.append({"check": f"{form['kind'].title()} form on {screen['screen_name']}",
                               "outcome": "protected by a CAPTCHA", "detail": "", "screen": screen["screen_name"]})
            return
        if form["kind"] == "login":
            self._login_checks(screen, form)
        elif form["kind"] == "search":
            self._search_check(screen, form)
        elif form["kind"] == "signup":
            self._positive_form_check(screen, form, "Sign-up")
        else:
            self._form_negative_checks(screen, form)
            self._positive_form_check(screen, form, "Form submission")

    def record_protected_controls(self, screen: dict):
        for element in screen.get("elements", []):
            if not usable(element) or element.get("input_capable") \
                    or not (element.get("clickable") or element.get("checkable")):
                continue
            words = label(element)
            reason = self.protected(words, navigation=element.get("navigation_role") == "menu_item") if words else ""
            if not reason:
                continue
            key = ("protected", family(element) if self.native else words.casefold())
            if key in self.seen:
                continue
            self.seen.add(key)
            check = f"Tap '{name(element)}' on {screen['screen_name']}"
            # The specific reason (checkout, a device feature, resetting the app) - not a generic "protected" text
            item = {"check": check, "outcome": "intentionally excluded", "detail": "not tapped",
                    "screen": screen["screen_name"], "reason": reason}
            self.tried.append(item)
            self._covered.add(id(item))
            self.cover("control", f"'{name(element)}'", "not tested", reason, where=screen["screen_name"])

    @staticmethod
    def _messages_from(changes):
        changes = [c for c in changes if c["kind"] in ("message", "appeared", "text", "alert")]
        return assertion_steps(changes, limit=2), changes

    def _messages(self, before, after):
        """What the app showed after a submission (inputs are never part of a diff: their contents stay private)."""
        return self._messages_from(self.diff(before, after))

    def _refused(self, screen, actions, stays, title, meta, accepted):
        """A submission any tester expects to be refused: the `stays` control must still be there afterwards.
        The message the app showed is added as an observed check; if that part does not replay, the universal
        check is kept alone. A missing form control is only reported as an app finding after a replay confirms it;
        a missing or ambiguous locator during replay stays inconclusive."""
        nav = self.nav(screen)
        before, after = self.observe_after(screen, actions)
        messages, changes = [], []
        if after is not None and not present(after, stays):
            after = self.uncovered(after)
        if after is not None and not present(after, stays):
            evidence = self.accepted_evidence(before, after)
            if not evidence:
                # Run android_20261109_181718_321078: the keyboard hid the password box after a wrong password and
                # this was reported as "Login with a wrong password was accepted". Missing is not accepted.
                self.tried.append({"check": title, "outcome": "inconclusive", "screen": screen["screen_name"],
                                   "detail": "", "reason": f"'{name(stays)}' could not be located after the "
                                                           "submission (keyboard or scroll); nothing shows it was "
                                                           "accepted"})
                return
            meta = {**meta, "evidence": evidence}
        if after is not None and present(after, stays):
            messages, changes = self._messages(before, after)
        alerts = [s for s in messages if s["action"] == "assert_alert"]
        base = nav + actions + alerts + [{"action": "assert_visible", "locator": stays["locators"][0]}]
        others = [s for s in messages if s["action"] != "assert_alert"]
        if messages and self.keep(self.build("form", f"{title}: {describe(changes)}", base + others), dict(meta)):
            return
        replay_meta = dict(meta)
        # Only with positive evidence (another screen, a logged-in sign, no error) does a missing control count
        failures = ("AssertionError", "ControlMissing") if meta.get("evidence") else ("AssertionError",)
        kept = self.keep(self.build("form", title, base), replay_meta, universal=True, failures=failures)
        if kept and str(replay_meta.get("discovery_replay", "")).startswith("failed twice:"):
            self.findings.append({"screen": screen["screen_name"], "finding": accepted,
                                  "detail": f"'{name(stays)}' remained absent on two clean replays; "
                                            + (meta.get("evidence") or "")})

    def uncovered(self, after: dict) -> dict:
        """The screen again after hiding the soft keyboard: it can cover a form's boxes after a submission."""
        hide = getattr(self.device, "hide_keyboard", None)
        if not hide:
            return after
        try:
            if hide():
                return self.device.observe()
        except Exception as error:
            from .android_runtime import device_unavailable
            if device_unavailable(error):
                raise
        return after

    @staticmethod
    def accepted_evidence(before: dict, after: dict) -> str:
        """Positive signs that a submission was accepted: another screen opened, or a logged-in sign (Log Out, My
        account) appeared - and no error text appeared. '' when there is none."""
        error = re.compile(r"\b(error|invalid|wrong|incorrect|required|not match|do not match|locked|failed|"
                           r"unsuccessful|try again)\b", re.I)
        old = {e.get("text") for e in before.get("elements", []) if e.get("visible")}
        new_texts = [e.get("text") or "" for e in after.get("elements", []) if e.get("visible") and e.get("text") not in old]
        if any(error.search(text) for text in new_texts):
            return ""
        signs = [label(e) for e in after.get("elements", []) if e.get("visible")
                 and re.search(r"\b(log ?out|sign ?out|my account|welcome)\b", label(e), re.I)
                 and not any(label(o) == label(e) for o in before.get("elements", []) if o.get("visible"))]
        if signs:
            return f"'{signs[0][:40]}' appeared"
        if after.get("screen_name") != before.get("screen_name") and not any(
                e.get("password") and e.get("visible") for e in after.get("elements", [])):
            return f"'{str(after.get('screen_name'))[:40]}' opened"
        return ""

    @staticmethod
    def _select_visible_account(screen: dict, username: str) -> list[dict]:
        """Use a matching app-provided account row when present (some demo apps auto-fill credentials)."""
        wanted = username.strip().casefold()
        if not wanted:
            return []
        matches = [element for element in screen.get("elements", [])
                   if usable(element) and element.get("clickable") and not element.get("input_capable")
                   and (element.get("text") or "").strip().casefold() == wanted]
        return [tap(matches[0])] if len(matches) == 1 else []

    @staticmethod
    def _select_locked_sample(screen: dict) -> list[dict]:
        """The app's sample row marked 'locked out', when the app says its rows fill in the login."""
        instruction = " ".join(element.get("text", "") for element in screen.get("elements", []) if element.get("visible"))
        if not re.search(r"automatically populate", instruction, re.I):
            return []
        rows = [e for e in screen.get("elements", []) if usable(e) and e.get("clickable") and not e.get("input_capable")
                and re.search(r"locked\s*out", label(e), re.I)]
        return [tap(rows[0])] if rows else []

    @staticmethod
    def _select_app_sample(screen: dict) -> list[dict]:
        """Select a demo account only when the app explicitly says the row auto-fills its credentials."""
        instruction = " ".join(element.get("text", "") for element in screen.get("elements", [])
                               if element.get("visible"))
        if not (re.search(r"select a username and password", instruction, re.I)
                and re.search(r"automatically populate", instruction, re.I)):
            return []
        elements = screen.get("elements", [])
        options = []
        for row in elements:
            if not usable(row) or not row.get("clickable") or row.get("input_capable"):
                continue
            row_id = (row.get("resource_id") or "").rsplit("/", 1)[-1]
            match = re.fullmatch(r"username(\d+)(?:tv)?", row_id, re.I)
            if not match or re.search(r"locked\s*out", label(row), re.I):
                continue
            suffix = match.group(1)
            if any((other.get("resource_id") or "").rsplit("/", 1)[-1].casefold() == f"password{suffix}tv".casefold()
                   and other.get("visible") and other.get("text") for other in elements):
                options.append((int(suffix), row))
        options.sort(key=lambda item: item[0])
        return [tap(options[0][1])] if options else []

    def _login_checks(self, screen, form):
        password, user, submit = form["password"], form["username"], form["submit"]
        meta = {"category": "form", "screen_id": screen["id"], "screen": screen["screen_name"],
                "element_ids": [e["id"] for e in (user, password, submit) if e], "source": "interaction"}
        # 1. Empty fields are refused
        empty = ([fill(user, "")] if user else []) + reach(submit) + [tap(submit)]
        self._refused(screen, empty, password, "Login with empty fields is refused",
                      {**meta, "expected": "The login form stays; the app does not log in with empty fields.",
                       "requirement": "Standard login behaviour (empty fields are refused)"},
                      "Login with empty fields was accepted")
        # 2. A wrong password is refused (the real test user when given, so only the password is wrong)
        account_user = self.account[0] if self.account else None
        app_sample = self._select_app_sample(screen) if not self.has_account else []
        if user:
            if self.has_account:
                select = self._select_visible_account(screen, self.secrets[account_user])
                wrong = select + [fill(user, secret_ref=account_user), fill(password, secret_ref=WRONG_PASSWORD)]
            elif app_sample:
                wrong = app_sample + [fill(password, secret_ref=WRONG_PASSWORD)]
            else:
                wrong = [fill(user, "qa.tester@example.com"), fill(password, secret_ref=WRONG_PASSWORD)]
            wrong += reach(submit) + [tap(submit)]
        else:
            wrong = [fill(password, secret_ref=WRONG_PASSWORD)] + reach(submit) + [tap(submit)]
        self._refused(screen, wrong, password, "Login with a wrong password is refused",
                      {**meta, "expected": "The login form stays and the app does not log in.",
                       "requirement": "Standard login behaviour (wrong credentials are refused)"},
                      "Login with a wrong password was accepted")
        # 2b. An app's own locked-out sample user ("alice@example.com (locked out)") shows its message
        locked = self._select_locked_sample(screen) if user else []
        if locked:
            steps = locked + reach(submit) + [tap(submit)]
            before, after = self.observe_after(screen, steps)
            if after is not None:
                changes = [c for c in self.diff(before, after) if c["kind"] in ("message", "appeared", "text", "alert")]
                checks = assertion_steps(changes, limit=2)
                title = "Login with the locked-out sample user is refused"
                if checks:
                    self.keep(self.build("form", f"{title}: {describe(changes)}", self.nav(screen) + steps + checks),
                              {**meta, "expected": "The locked-out user cannot log in and the app says why.",
                               "requirement": "The app's own locked-out sample user"})
                else:
                    self.tried.append({"check": title, "outcome": "no visible change", "detail": "",
                                       "screen": screen["screen_name"]})
        # 3. The account logs in: the person's test account, or the one test mode just registered
        if user and (self.has_account or app_sample):
            account_steps = self.account_steps(screen, form) if self.has_account else app_sample
            steps = self.nav(screen) + account_steps + reach(submit) + [tap(submit)]
            steps += self.login_evidence(screen, steps, password)
            which = ("the test account" if self.given_account else "the app's sample user" if not self.has_account
                     else "the account it just registered")
            flow = self.build("login", f"Login with {which} succeeds", steps, authentication=True)
            login_meta = {**meta, "category": "login", "expected": f"Logging in with {which} works: the login form is replaced.",
                          "requirement": "The app-provided or supplied test account can log in"}
            if self.keep(flow, login_meta, universal=True) and login_meta.get("discovery_replay") == "passed":
                self.after_login(screen, flow)
        elif user and not self.has_account:
            self.tried.append({"check": "Login with a test account", "outcome": "not attempted",
                               "reason": "no test account was given and none could be registered",
                               "detail": "", "screen": screen["screen_name"]})

    def account_steps(self, screen: dict, form: dict) -> list[dict]:
        user_ref, password_ref = self.account
        return (self._select_visible_account(screen, self.secrets[user_ref])
                + [fill(form["username"], secret_ref=user_ref), fill(form["password"], secret_ref=password_ref)])

    def login_evidence(self, screen: dict, steps: list[dict], password: dict) -> list[dict]:
        """What proves the login worked: the login form is replaced."""
        return [{"action": "assert_not_visible", "locator": password["locators"][0]}]

    def after_login(self, screen: dict, flow: dict):
        discover = getattr(self.device, "on_authenticated", None)
        if discover:
            self.attempt("Explore screens after test-account login", discover, flow, area="login")

    def search_word(self) -> str:
        return "test"

    def _search_check(self, screen, form):
        box = next((e for e in form["inputs"] if SEARCH.search(label(e))), form["inputs"][0])
        word = self.search_word()
        steps = [fill(box, word)] + reach(form["submit"]) + [tap(form["submit"])]
        before, after = self.observe_after(screen, steps)
        if after is None:
            return
        changes = self.diff(before, after)
        checks = assertion_steps(changes)
        if checks:
            self.keep(self.build("form", f"Search for '{word}' on {screen['screen_name']} shows results",
                                 self.nav(screen) + steps + checks),
                      {"category": "form", "screen_id": screen["id"], "screen": screen["screen_name"],
                       "element_ids": [box["id"], form["submit"]["id"]], "source": "interaction",
                       "expected": f"Searching for '{word}' shows the results observed during exploration "
                                   f"({describe(changes)}).",
                       "requirement": "Observed app behaviour on a test build (regression)"})
        else:
            self.tried.append({"check": f"Search for '{word}' on {screen['screen_name']}", "outcome": "no visible change",
                               "detail": "", "screen": screen["screen_name"]})

    def fill_valid(self, element: dict, action_name: str) -> dict:
        """A valid value for this box: generated test data (example.com addresses), never a real person's."""
        from .testdata import BASE
        kind = field_kind(element)
        hint = label(element).casefold()
        if kind == "email":
            return fill(element, secret_ref=SIGNUP_EMAIL)
        if kind == "password":
            return fill(element, secret_ref=STRONG_PASSWORD)
        accepted = next((item["value"] for item in BASE.get(kind, []) if item["expect"] == "accept"), "QA Tester")
        if re.search(r"\b(user ?name|login ?name)\b", hint):
            return fill(element, secret_ref=SIGNUP_USERNAME)
        if action_name != "Sign-up" and kind in ("text", "names"):
            accepted = accepted + " " + secrets.token_hex(3)
        return fill(element, accepted)

    def _positive_form_check(self, screen, form, action_name):
        """Try valid form data in test mode, without touching the actions test mode never uses."""
        inputs, submit = form["inputs"], form["submit"]
        # Each control's words apart: the last word of one box and the first of the next must not make a phrase
        context = " | ".join([label(submit), *(label(element) for element in inputs)])
        password_change = action_name != "Sign-up" and any(element.get("password") for element in inputs)
        payment_form = any(field_kind(element) in PAYMENT_INPUTS for element in inputs)
        reason = self.protected(context) or ("changing the test account's password is never tested" if password_change
                                             else "payment forms are never filled" if payment_form else "")
        if reason:
            self.tried.append({"check": f"{action_name} on {screen['screen_name']}",
                               "outcome": "intentionally excluded",
                               "detail": "This form appears to perform a protected payment, order, deletion, reset, logout, password-change, or crash action.",
                               "screen": screen["screen_name"], "reason": reason})
            return
        actions = [self.fill_valid(element, action_name) for element in inputs]
        actions += [tap(box) for box in form.get("ticks", [])]  # required boxes such as "I agree to the terms"
        actions += form.get("choices", [])  # a required drop-down still on its empty first option
        actions += reach(submit) + [tap(submit)]
        before, after = self.observe_after(screen, actions)
        if after is None:
            self.tried.append({"check": f"{action_name} with valid details on {screen['screen_name']}",
                               "outcome": "opens another app", "detail": "Not followed.",
                               "screen": screen["screen_name"]})
            return

        title = f"{action_name} with valid details succeeds on {screen['screen_name']}"
        first = inputs[0]
        private = [value for value in self.secrets.values() if value]
        changes = self.diff(before, after)
        alerts = [{"action": "assert_alert", "value": c["text"]} for c in changes
                  if c["kind"] == "alert" and not any(v.casefold() in c["text"].casefold() for v in private)][:1]
        checks = []
        if not present(after, first):
            checks = [{"action": "assert_not_visible", "locator": first["locators"][0]}]
        for change in changes:
            # A successful registration may keep the form open and show a status.
            # Never copy an email, username, or password into an assertion/report.
            if change["kind"] == "alert":
                continue
            element = change.get("element") or {}
            message = element.get("text", "") or change.get("after", "")
            if (change["kind"] in ("message", "appeared", "text", "title") and SUCCESS.search(message)
                    and not any(value.casefold() in message.casefold() for value in private)):
                checks += assertion_steps([change], limit=1)
                break
        success_message = bool(alerts and SUCCESS.search(alerts[0]["value"]))
        if not checks and not success_message:
            # A valid test submission that leaves the form open without a success
            # signal is a finding; retain an assertion so the result cannot go green.
            checks = [{"action": "assert_not_visible", "locator": first["locators"][0]}]
            self.findings.append({"screen": screen["screen_name"],
                                  "finding": f"Valid {action_name.casefold()} details did not produce an observable success",
                                  "detail": "The form remained open without a non-sensitive success result."})
        category = "signup" if action_name == "Sign-up" else "form"
        flow = self.build(category, title, self.nav(screen) + actions + alerts + checks)
        flow_meta = {"category": category, "screen_id": screen["id"], "screen": screen["screen_name"],
                     "element_ids": [e["id"] for e in [*inputs, submit]], "source": "interaction",
                     "expected": f"{action_name} with valid data is accepted and the form closes or shows a success result.",
                     "requirement": "Valid form submission on an authorized test build"}
        if self.keep(flow, flow_meta, universal=True) and action_name == "Sign-up" \
                and flow_meta.get("discovery_replay") == "passed" and not self.has_account:
            self.remember_account(actions)

    def remember_account(self, actions: list[dict]):
        """The sign-up just worked twice: log in with the account the replay registered (no test account given)."""
        refs = {step.get("secret_ref") for step in actions}
        user_ref = SIGNUP_USERNAME if SIGNUP_USERNAME in refs else SIGNUP_EMAIL if SIGNUP_EMAIL in refs else None
        if user_ref is None or STRONG_PASSWORD not in refs:
            return
        self.secrets[ACCOUNT_USERNAME] = self.secrets[user_ref]
        self.secrets[ACCOUNT_PASSWORD] = self.secrets[STRONG_PASSWORD]
        self.account = (ACCOUNT_USERNAME, ACCOUNT_PASSWORD)
        remember = getattr(self.device, "remember_secret", None)
        if remember:
            remember(ACCOUNT_USERNAME, self.secrets[ACCOUNT_USERNAME])
            remember(ACCOUNT_PASSWORD, self.secrets[ACCOUNT_PASSWORD])

    def saved_secrets(self) -> dict:
        """The generated account the final run needs again (private file only; never a public report)."""
        return {name: self.secrets[name] for name in (ACCOUNT_USERNAME, ACCOUNT_PASSWORD)
                if name in self.secrets and self.account == (ACCOUNT_USERNAME, ACCOUNT_PASSWORD)}

    def _form_negative_checks(self, screen, form):
        """Only values a form must refuse: nothing valid is ever submitted (no account or record is created)."""
        from .testdata import BASE
        submit, first = form["submit"], form["inputs"][0]
        nav = self.nav(screen)
        meta = {"category": "form", "screen_id": screen["id"], "screen": screen["screen_name"],
                "element_ids": [e["id"] for e in form["inputs"]] + [submit["id"]], "source": "interaction",
                "requirement": "Observed form validation on a test build (regression)"}
        empty = [fill(e, "") for e in form["inputs"] if not e.get("password")] + reach(submit) + [tap(submit)]
        tries = [("empty", "Submitting the form empty is refused", empty)]
        target = next((e for e in form["inputs"] if not e.get("password")
                       and any(v["expect"] == "reject" for v in BASE.get(field_kind(e), []))), None)
        if target is not None:
            kind = field_kind(target)
            bad = next(v for v in BASE[kind] if v["expect"] == "reject")
            steps = []
            for element in form["inputs"]:
                if element is target:
                    steps.append(fill(element, bad["value"]))
                elif element.get("password"):
                    steps.append(fill(element, secret_ref=STRONG_PASSWORD))
                else:
                    good = next((v for v in BASE.get(field_kind(element), []) if v["expect"] == "accept"), {"value": "QA test"})
                    steps.append(fill(element, good["value"]))
            steps += reach(submit) + [tap(submit)]
            tries.append(("invalid", f"An invalid {kind.replace('_', ' ')} ('{bad['value']}') in '{name(target)}' is refused", steps))
        for _, title, steps in tries:
            before, after = self.observe_after(screen, steps)
            if after is None:
                continue
            if not present(after, first):
                self.findings.append({"screen": screen["screen_name"], "finding": title.replace("is refused", "was accepted"),
                                      "detail": "The form disappeared; review whether this input should be allowed."})
                self.tried.append({"check": title, "outcome": "finding", "screen": screen["screen_name"],
                                   "reason": "the form accepted it and disappeared - review whether this should be "
                                             "allowed", "detail": ""})
                continue
            checks, changes = self._messages(before, after)
            alerts = [s for s in checks if s["action"] == "assert_alert"]
            others = [s for s in checks if s["action"] != "assert_alert"]
            if checks:
                self.keep(self.build("form", f"{title}: {describe(changes)}",
                                     nav + steps + alerts + [{"action": "assert_visible", "locator": first["locators"][0]}] + others),
                          {**meta, "expected": f"The form stays and shows its validation message ({describe(changes)})."})
            else:
                self.tried.append({"check": title, "outcome": "no visible change", "detail": "",
                                   "screen": screen["screen_name"]})

    def device_checks(self):
        """Rotation, background/resume and Back: the screen a tester was on must still be there afterwards."""
        launch = self.screens[0]
        deeper = [s for s in self.screens[1:] if len(s.get("path", [])) == 1 and "drawer" not in (s.get("identity") or [])
                  and "dialog" not in (s.get("identity") or [])][:1]
        shared = {family(e) for e in launch["elements"] if e.get("visible")}
        for screen in [launch, *deeper]:
            mark = anchor(screen, set() if screen is launch else shared)
            if mark is None:
                continue
            nav = self.nav(screen)
            meta = {"category": "device", "screen_id": screen["id"], "screen": screen["screen_name"],
                    "element_ids": [mark["id"]], "source": "interaction"}
            self.keep(self.build("device", f"{screen['screen_name']} survives rotating the phone",
                                 nav + [{"action": "rotate", "value": "landscape"}, {"action": "rotate", "value": "portrait"}]
                                 + anchor_checks(mark)),
                      {**meta, "expected": f"After rotating to landscape and back, '{name(mark)}' is still shown.",
                       "requirement": "Standard mobile behaviour (screen state survives rotation)"}, universal=True)
            self.keep(self.build("device", f"{screen['screen_name']} comes back after leaving the app",
                                 nav + [{"action": "background", "value": "3"}] + anchor_checks(mark)),
                      {**meta, "expected": f"After 3 seconds in the background, the app returns to '{name(mark)}'.",
                       "requirement": "Standard mobile behaviour (the app resumes where it was)"}, universal=True)
        start = anchor(launch)
        for screen in deeper:
            if start is None:
                break
            before, after = self.observe_after(screen, [{"action": "back"}])
            if after is not None and present(after, start):
                self.keep(self.build("device", f"Back from {screen['screen_name']} returns to {launch['screen_name']}",
                                     self.nav(screen) + [{"action": "back"}] + anchor_checks(start)),
                          {"category": "device", "screen_id": screen["id"], "screen": screen["screen_name"],
                           "element_ids": [start["id"]], "source": "interaction",
                           "expected": f"The system Back button returns to {launch['screen_name']} (as observed).",
                           "requirement": "Observed navigation on a test build (regression)"})

    # -------- AI journeys
    def ai_journeys(self, ask, requirements: str = ""):
        """Ask the AI for end-to-end journeys over the observed controls; keep only the ones that pass a replay."""
        import json
        from typing import Literal

        from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, create_model, model_validator

        screen_alias = {f"S{i}": s for i, s in enumerate(self.screens[:8], 1)}
        element_alias, inventory = {}, []
        for alias, screen in screen_alias.items():
            listed = []
            for element in screen["elements"]:
                if not usable(element) or not (label(element) or element.get("text")):
                    continue
                if element.get("clickable") and not element.get("input_capable") and self.protected(label(element)):
                    continue
                eid = f"E{len(element_alias) + 1}"
                element_alias[eid] = (screen, element)
                listed.append({"id": eid, "type": "input" + (" (password)" if element.get("password") else "")
                               if element.get("input_capable") else "button" if element.get("clickable") else "text",
                               "label": name(element)})
                if len(listed) >= 15:
                    break
            inventory.append({"screen": alias, "name": screen["screen_name"], "controls": listed})
        if not element_alias:
            return
        observed = [f"{item['check']} -> {item['outcome']}" for item in self.tried][:20]
        references = tuple(element_alias)

        class Step(BaseModel):
            model_config = ConfigDict(extra="forbid")
            action: Literal["tap", "fill", "back", "assert_visible", "assert_text", "assert_not_visible"]
            element: str | None = None
            value: str | None = Field(default=None, max_length=100)

        bound = create_model("BoundStep", __base__=Step, element=(Literal[references] | None, None))

        class Journey(BaseModel):
            model_config = ConfigDict(extra="forbid")
            title: str = Field(min_length=3, max_length=140)
            start: Literal[tuple(screen_alias)]
            steps: list[bound] = Field(min_length=2, max_length=12)

        one = TypeAdapter(Journey)

        class JourneyBatch(BaseModel):
            """{"journeys": [...]} as asked. Providers sometimes answer a bare list, or wrap the list in another
            single key ({"user_journeys": [...]}): both are accepted. Invalid journeys are left out, not fatal."""
            model_config = ConfigDict(extra="ignore")
            journeys: list[Journey] = Field(default_factory=list, max_length=4)

            @model_validator(mode="before")
            @classmethod
            def unwrap(cls, data):
                if isinstance(data, list):
                    data = {"journeys": data}
                elif isinstance(data, dict) and not isinstance(data.get("journeys"), list):
                    lists = [value for value in data.values() if isinstance(value, list)]
                    if len(lists) == 1:
                        data = {"journeys": lists[0]}
                if not isinstance(data, dict) or not isinstance(data.get("journeys"), list):
                    raise ValueError('Return an object {"journeys": [...]}')
                kept = []
                for item in data["journeys"]:
                    try:
                        kept.append(one.validate_python(item))
                    except ValidationError:
                        continue
                if data["journeys"] and not kept:
                    raise ValueError("None of the journeys matched the requested structure")
                return {"journeys": kept[:4]}

        prompt = (
            "You are a senior mobile QA engineer testing a TEST BUILD of an Android app"
            + (" (a test website in Android Chrome)" if self.web else "") + ". Propose at most 4 end-to-end user "
            "journeys a real tester would run (for example: add an item, open the cart, check the item is listed). "
            "Use ONLY the S/E references below; each journey starts on its `start` screen. Actions: tap, fill (value = a "
            "realistic test value; for a password field use exactly TEST_PASSWORD and for its username TEST_USERNAME"
            + ("" if self.has_account else " - no test account is available, so do not log in") + "), back, assert_visible, "
            "assert_text (value = a text from the inventory or the observations), assert_not_visible. Every journey ends "
            "with assertions of its result. Never pay, check out, place an order, delete an account or share. "
            'Return JSON only, exactly this shape: {"journeys": [{"title": "...", "start": "S1", "steps": '
            '[{"action": "tap", "element": "E1"}, {"action": "assert_visible", "element": "E2"}]}]}\n'
        )
        prompt += json.dumps({"screens": inventory, "observations": observed, "requirements": requirements[:3000]})
        result = ask(prompt, JourneyBatch)
        journeys = result.journeys if isinstance(result, JourneyBatch) else JourneyBatch.model_validate(result).journeys
        for journey in journeys[:4]:
            self.attempt("AI journey: " + journey.title, self._journey, journey, screen_alias, element_alias,
                         area="journey", where=screen_alias[journey.start]["screen_name"])

    def _journey(self, journey, screen_alias, element_alias):
        screen = screen_alias[journey.start]
        steps, ids = self.nav(screen), []
        user_ref, password_ref = self.account or (TEST_USERNAME, TEST_PASSWORD)
        for step in journey.steps:
            if step.action == "back":
                steps.append({"action": "back"})
                continue
            if step.element is None:
                self.tried.append({"check": "AI journey: " + journey.title, "outcome": "rejected", "detail": "A step had no control."})
                return
            _, element = element_alias[step.element]
            ids.append(element["id"])
            if step.action == "tap":
                if self.protected(label(element)):
                    self.tried.append({"check": "AI journey: " + journey.title, "outcome": "rejected",
                                       "detail": f"'{name(element)}' is not tapped while acting like a user."})
                    return
                steps += reach(element) + [tap(element)]
            elif step.action == "fill":
                value = (step.value or "").strip()
                if element.get("password") or value == "TEST_PASSWORD":
                    if not self.has_account or value != "TEST_PASSWORD":
                        self.tried.append({"check": "AI journey: " + journey.title, "outcome": "rejected",
                                           "detail": "Password fields use only the private test account."})
                        return
                    steps.append(fill(element, secret_ref=password_ref))
                elif value == "TEST_USERNAME":
                    if not self.has_account:
                        return
                    steps.append(fill(element, secret_ref=user_ref))
                else:
                    steps.append(fill(element, value))
            elif step.action == "assert_text":
                if not step.value:
                    return
                steps.append({"action": "assert_text", "locator": element["locators"][0], "value": step.value})
            else:
                steps.append({"action": step.action, "locator": element["locators"][0]})
        if not any(s["action"].startswith("assert_") for s in steps):
            return
        authentication = any(s.get("secret_ref") == password_ref for s in steps)
        flow = self.build("journey", "Journey: " + journey.title, steps, authentication=authentication)
        self.keep(flow, {"category": "journey", "screen_id": screen["id"], "screen": screen["screen_name"],
                         "element_ids": ids, "source": "ai",
                         "expected": "The AI-drafted journey's result, confirmed by a replay on this build.",
                         "requirement": "AI-drafted user journey, verified by replay (regression)"})

    # -------- everything, in order
    def plan(self):
        """The checks, in order, as they become known: forms, then undoable actions, then phone checks. A generator,
        because a login reveals new screens while the plan runs."""
        login_found = False
        planned = set()
        for screen in self.screens:
            form = find_form(screen, self.native)
            if form:
                login_found = login_found or form["kind"] == "login"
                yield {"area": "form", "name": f"{form['kind'].title()} form on {screen['screen_name']}",
                       "where": screen["screen_name"], "run": self.form_checks, "args": (screen, form)}
        if self.has_account and not login_found:
            self.tried.append({"check": "Login with the supplied test account", "outcome": "not attempted",
                               "detail": "No discovered screen had a password field and a Login/Sign in button. "
                                         "The supplied account was not entered; check discovery gaps for an unreached login screen."})
        for screen in self.screens:
            for element in reversible_candidates(screen, self.native):
                if family(element) in planned:
                    continue
                planned.add(family(element))
                yield {"area": "control", "name": f"Tap '{name(element)}' on {screen['screen_name']}",
                       "where": screen["screen_name"], "run": self.tap_check, "args": (screen, element)}
        yield {"area": "phone", "name": "Rotation, background and Back checks", "where": self.screens[0]["screen_name"],
               "run": self.device_checks, "args": ()}

    def execute(self, plan) -> str:
        """Run each planned check; when the budget ends, every check not reached is listed with the reason."""
        from .android_web import BotCheckBlocked

        plan = iter(plan)
        for item in plan:
            try:
                self.attempt(item["name"], item["run"], *item["args"], area=item["area"], where=item.get("where", ""))
            except (Budget, BotCheckBlocked) as reason:
                for rest in plan:
                    self.cover(rest["area"], rest["name"], "not tested", budget_reason(str(reason)), where=rest.get("where", ""))
                return str(reason)
        return ""

    def run(self, ask=None, requirements: str = "") -> str:
        """Forms, then undoable actions, then phone checks, then AI journeys. Returns why it stopped ('' = done)."""
        self.reserve = 6 if ask else 0  # room kept for the AI journeys' replays
        for screen in self.screens:
            self.record_protected_controls(screen)
        stopped = self.execute(self.plan())
        return self.journeys(ask, requirements, stopped)

    def journeys(self, ask, requirements: str, stopped: str) -> str:
        if ask and not self.device.stop_path.exists() and not stopped.startswith("User-like testing time"):
            self.reserve = 0
            try:
                self.ai_journeys(ask, requirements)
            except Budget as reason:
                stopped = stopped or str(reason)
            except Exception as error:  # an AI failure never fails the run: rules-based checks stand
                from .android_runtime import device_unavailable
                if device_unavailable(error):
                    raise
                self.tried.append({"check": "AI journeys", "outcome": "AI not used", "detail": redact(str(error))[:200]})
                self.cover("journey", "AI journeys", "not tested", PLAIN["AI not used"] + ": " + redact(str(error))[:160])
        elif not ask:
            self.cover("journey", "AI journeys", "not tested", "the AI is off for this run; the rule-based checks stand")
        return stopped

    def contract(self) -> dict:
        return parse_contract({**self.base, "flows": [item["flow"] for item in self.flows]}).model_dump(mode="json")


def auto_cases(auto_flows: list[dict]) -> list[dict]:
    """Test cases for the kept flows. They change app data, so each starts from cleared data and runs last."""
    cases = []
    for item in auto_flows:
        flow, meta = item["flow"], item["meta"]
        universal = meta.get("universal")
        cases.append({
            "id": "android_" + flow["id"],
            "title": flow["title"],
            "kind": "interaction",
            "type": "workflow",
            "category": meta.get("category", "user_action"),
            "screen_id": meta.get("screen_id", "launch"),
            "element_ids": meta.get("element_ids", []),
            "priority": "high" if meta.get("category") in ("login", "form") or universal else "medium",
            "expected": meta.get("expected", ""),
            "requirement": meta.get("requirement", ""),
            "generation_source": meta.get("source", "interaction"),
            "functionality_status": "confirmed" if universal else "inferred",
            "reset_app_data": True,
            "auto_flow_id": flow["id"],
            "discovery_replay": meta.get("discovery_replay", ""),
            "plan": [["assert_flow", [flow["id"]]]],
        })
    return cases
