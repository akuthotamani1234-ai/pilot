"""Application-specific expected behavior, shared by native, hybrid and browser QA."""

import ast
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, model_validator

from .safety import check_target, is_metadata_host

ID = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
SECRET_REF = r"^BLOWAI_SECRET_[A-Z0-9_]{1,80}$"  # noqa: S105 - environment reference pattern, not a credential
# Non-test-mode discovery also hard-blocks only checkout / payment (exhaustive explore).
IRREVERSIBLE = re.compile(
    r"\b(pay|pay ?now|payments?|purchase|buy|buy ?now|checkout|check ?out|"
    r"place (?:an |the |your |my )?order|(?:confirm|submit|complete|finish) (?:the |your |my |this )?"
    r"(?:order|purchase|payment)|order now|credit card|card details|"
    r"apple ?pay|google ?pay|pay ?pal)\b",
    re.I,
)
# Test mode: explore until exhausted; only checkout / payment stay blocked.
TEST_MODE_NEVER = tuple((reason, re.compile(r"\b(?:" + words + r")\b", re.I)) for reason, words in (
    ("checkout, payment and placing an order are never tested",
     r"check ?out|pay|pay ?now|payments?|pay ?pal|apple ?pay|google ?pay|purchase|buy|buy ?now|"
     r"place (?:an |the |your |my )?order|(?:confirm|submit|complete|finish) (?:the |your |my |this )?"
     r"(?:order|purchase|payment)|order now|re-?order|credit card|card details|"
     r"book now|reserve now|"
     r"book (?:a |the |this |your )?(?:room|table|flight|ticket|seat|stay|trip|appointment)"),
    ("paid subscriptions and upgrades are never started",
     r"(?:paid|premium|monthly|yearly|annual) (?:subscription|plan|membership)|"
     r"start (?:a |your |the )?(?:free )?trial|subscribe (?:now|to (?:premium|pro|plus))"),
))
# Native-only: leaving the app into the camera / contacts / system prompt is still skipped (not payment, but
# not an in-app screen). Exhaustive exploration stays inside the app under test.
TEST_MODE_NEVER_NATIVE = ("device features that leave the app (camera, scanner, contacts) are not followed out",
                          re.compile(r"\b(camera|photo|gallery|microphone|location|locate|contacts?|scanner|scan|"
                                     r"qr|finger ?print|biometrics?|face ?id|usb)\b", re.I))
DEVICE_ACTIONS = ("back", "rotate", "background", "hide_keyboard")


def never_in_test_mode(text: str, native: bool = False) -> str:
    """'' when a tester may press a control with this label in test mode, else the plain reason it is never pressed.
    Outside test mode IRREVERSIBLE still hard-blocks checkout/payment only. (A menu item that
    only opens an app's own screen - "QR Code Scanner" - is checked with native=False: the screen may open, its
    device feature is never used.)"""
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text or "").replace("_", " ").replace("-", " ")
    for reason, pattern in TEST_MODE_NEVER:
        if pattern.search(words):
            return reason
    if native and TEST_MODE_NEVER_NATIVE[1].search(words):
        return TEST_MODE_NEVER_NATIVE[0]
    return ""


def protected(text: str, test_mode: bool = False, native: bool = True) -> str:
    """Why a control is never pressed ('' = it may be): the test-mode rules, or the stricter default."""
    if test_mode:
        return never_in_test_mode(text, native)
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text or "").replace("_", " ")
    return "Matches a protected-action rule; it was not tapped." if IRREVERSIBLE.search(words) else ""
ANDROID_TEST_PERMISSIONS = {
    'android.permission.CAMERA', 'android.permission.RECORD_AUDIO',
    'android.permission.ACCESS_FINE_LOCATION', 'android.permission.ACCESS_COARSE_LOCATION',
    'android.permission.POST_NOTIFICATIONS', 'android.permission.READ_MEDIA_IMAGES',
    'android.permission.READ_MEDIA_VIDEO', 'android.permission.READ_MEDIA_VISUAL_USER_SELECTED',
    'android.permission.READ_EXTERNAL_STORAGE',
    'android.permission.READ_MEDIA_AUDIO',
}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Locator(Model):
    strategy: Literal["accessibility_id", "resource_id", "text", "xpath", "css"]
    value: str = Field(min_length=1, max_length=500)


class PermissionPolicy(Model):
    approved: bool = False
    app_label: str = Field(min_length=1, max_length=100)
    allowed: list[str] = Field(min_length=1, max_length=10)
    emulator_only: Literal[True] = True
    restore_after_flow: Literal[True] = True

    @model_validator(mode='after')
    def supported_permissions(self):
        if len(set(self.allowed)) != len(self.allowed) or not set(self.allowed) <= ANDROID_TEST_PERMISSIONS:
            raise ValueError('List each supported Android test permission once')
        return self


class Step(Model):
    action: Literal[
        "tap",
        "fill",
        "select",
        "assert_text",
        "assert_visible",
        "assert_not_visible",
        "assert_enabled",
        "assert_screen",
        "context",
        "swipe",
        "drag",
        "scroll_to",
        "assert_checked",
        "relaunch",
        "permission_state",
        "request_permission",
        "handle_permission",
        "assert_permission",
        # Things a manual tester does with the phone itself (Android only)
        "back",
        "rotate",
        "background",
        "hide_keyboard",
        "long_press",
        # Android Chrome: open a page of the approved website, and check (then close) a browser message (alert)
        "open",
        "assert_alert",
    ]
    locator: Locator | None = None
    target: Locator | None = None
    value: str | None = Field(default=None, max_length=1000)
    secret_ref: str | None = Field(default=None, pattern=SECRET_REF)
    purpose: Literal["navigation", "test_form"] = "navigation"
    sensitive: bool = False
    permission: str | None = None
    permissions: list[str] | None = Field(default=None, min_length=1, max_length=10)

    @model_validator(mode="after")
    def valid_step(self, info: ValidationInfo):
        if self.action in ("open", "assert_alert"):
            if self.locator is not None or self.target is not None:
                raise ValueError("Open and assert_alert steps act on the browser, not a control")
            if not self.value:
                raise ValueError("Open needs a page address; assert_alert needs the expected message")
            if self.action == "open":
                parts = urlsplit(self.value)
                if parts.scheme not in ("http", "https") or parts.username or parts.password:
                    raise ValueError("Open needs an http(s) address without credentials")
                check_target(self.value, resolve=False)
        if self.permissions is not None and (self.action != 'request_permission'
                or self.permission not in self.permissions or len(set(self.permissions)) != len(self.permissions)
                or not set(self.permissions) <= ANDROID_TEST_PERMISSIONS):
            raise ValueError('Batch permission requests must list each supported permission once, including the selected permission')
        permission_actions = {'permission_state', 'request_permission', 'handle_permission', 'assert_permission'}
        if self.action in permission_actions:
            if self.permission not in ANDROID_TEST_PERMISSIONS:
                raise ValueError('Choose a supported Android test permission')
            choices = {'permission_state': {'granted', 'denied'}, 'handle_permission': {'allow', 'allow_once', 'allow_while_using', 'deny'},
                       'assert_permission': {'granted', 'denied'}}
            if self.action in choices and self.value not in choices[self.action]:
                raise ValueError('Choose a valid permission state or prompt response')
        elif self.permission is not None:
            raise ValueError('Permission names belong only to permission steps')
        if self.action in ("swipe", "scroll_to") and self.value not in ("up", "down", "left", "right"):
            raise ValueError("Swipe needs an up, down, left or right direction")
        if self.action in ("drag", "scroll_to") and self.target is None:
            raise ValueError("Drag and scroll_to need a destination locator")
        if self.target is not None and self.action not in ("drag", "scroll_to"):
            raise ValueError("Only drag and scroll_to steps accept a destination locator")
        if self.action in DEVICE_ACTIONS:
            if self.locator is not None:
                raise ValueError("Back, rotate, background and hide_keyboard steps act on the phone, not a control")
            if self.action == "rotate" and self.value not in ("portrait", "landscape"):
                raise ValueError("Rotate needs portrait or landscape")
            if self.action == "background":
                seconds = self.value or ""
                if not seconds.isdigit() or not 1 <= int(seconds) <= 30:
                    raise ValueError("Background needs a whole number of seconds between 1 and 30")
            if self.action in ("back", "hide_keyboard") and self.value is not None:
                raise ValueError("Back and hide_keyboard steps take no value")
        if self.action not in ("context", "assert_screen", "relaunch", "permission_state", "handle_permission", "assert_permission",
                               "open", "assert_alert", *DEVICE_ACTIONS) and self.locator is None:
            raise ValueError("This step needs a locator")
        if self.action in ("context", "assert_screen", "assert_text", "select") and self.value is None:
            raise ValueError("This step needs an expected value")
        if self.action == "context" and self.value not in ("native", "webview"):
            raise ValueError("Context must be native or webview")
        if self.action == "fill":
            if (self.value is None) == (self.secret_ref is None):
                raise ValueError("Fill needs exactly one value or secret_ref")
            password = self.sensitive or bool(re.search(r"password|passwd|token|secret", self.locator.value, re.I))
            if password and not self.secret_ref:
                raise ValueError("Sensitive fields require a secret_ref, never an inline value")
        elif self.secret_ref or self.sensitive:
            raise ValueError("Secret references belong only to fill steps")
        # Flows made in test mode use the test-mode rules (a cart's Remove button may be pressed, checkout never);
        # every other contract keeps the stricter rule. The runtime checks the live control again.
        test_mode = bool((info.context or {}).get("test_mode"))
        # A test-mode tap marked "navigation" only opens an app's own screen (a "QR Code Scanner" menu item): the
        # device-feature words are not checked for it; checkout and the rest of the never-list still are.
        if self.action in ("tap", "long_press") and protected(
                self.locator.value, test_mode,
                native=self.locator.strategy != "css" and not (test_mode and self.purpose == "navigation")):
            raise ValueError("Irreversible actions cannot be approved by a QA contract")
        if self.action == "assert_enabled" and self.value not in (None, "true", "false"):
            raise ValueError("Enabled expectations must be true or false")
        if self.action == 'assert_checked' and self.value not in (None, 'true', 'false'):
            raise ValueError('Checked expectations must be true or false')
        return self


class Flow(Model):
    id: str = Field(pattern=ID)
    title: str = Field(min_length=1, max_length=180)
    approved: bool = False
    authentication: bool = False
    steps: list[Step] = Field(min_length=1, max_length=40)
    setup_flow: str | None = Field(default=None, pattern=ID)
    timeout_s: int = Field(default=90, ge=10, le=300)

    @model_validator(mode="after")
    def has_oracle(self):
        if not any(s.action.startswith("assert_") for s in self.steps):
            raise ValueError("Every flow needs an explicit assertion of its result")
        if self.authentication:
            submissions = [
                i for i, step in enumerate(self.steps) if step.action == "tap" and step.purpose == "test_form"
            ]
            if not submissions or not any(
                step.action in ("assert_screen", "assert_text", "assert_not_visible")
                for step in self.steps[submissions[-1] + 1 :]
            ):
                raise ValueError("Authentication needs a submission followed by explicit result evidence")
        return self


class NumberSource(Model):
    locator: Locator | None = None
    number: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def one_source(self):
        if (self.locator is None) == (self.number is None):
            raise ValueError("A number source needs exactly one locator or number")
        if self.number is not None:
            finite_decimal(self.number)
        return self


class Rule(Model):
    id: str = Field(pattern=ID)
    title: str = Field(min_length=1, max_length=180)
    setup_flow: str | None = Field(default=None, pattern=ID)
    actual: Locator
    variables: dict[str, NumberSource] = Field(min_length=1, max_length=12)
    expression: str = Field(min_length=1, max_length=300)
    tolerance: str = "0.01"

    @model_validator(mode="after")
    def safe_expression(self):
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", k) for k in self.variables):
            raise ValueError("Invalid business-rule variable name")
        evaluate(self.expression, {k: Decimal(1) for k in self.variables}, validate_only=True)
        if not Decimal(0) <= finite_decimal(self.tolerance) <= Decimal(1):
            raise ValueError("Tolerance must be between zero and one")
        return self


class BackendCheck(Model):
    id: str = Field(pattern=ID)
    title: str = Field(min_length=1, max_length=180)
    kind: Literal["http", "sqlite"]
    setup_flow: str | None = Field(default=None, pattern=ID)
    url: str | None = Field(default=None, max_length=2000)
    token_ref: str | None = Field(default=None, pattern=SECRET_REF)
    status: int = Field(default=200, ge=100, le=599)
    json_pointer: str = Field(default="", max_length=500)
    database_ref: str | None = Field(default=None, pattern=r"^BLOWAI_DB_[A-Z0-9_]{1,80}$")
    query: str | None = Field(default=None, max_length=2000)
    parameters: list[Any] = Field(default_factory=list, max_length=30)
    expected: Any

    @model_validator(mode="after")
    def read_only(self):
        if isinstance(self.expected, (dict, list)) or any(isinstance(p, (dict, list)) for p in self.parameters):
            raise ValueError("Backend checks compare one scalar value")
        if self.kind == "http":
            if not self.url or self.database_ref or self.query:
                raise ValueError("HTTP checks need a URL and cannot contain SQL")
            check_target(self.url, resolve=False)
            if self.json_pointer and not self.json_pointer.startswith("/"):
                raise ValueError("JSON pointers must be empty or start with /")
        else:
            if not self.database_ref or not self.query or self.url or self.token_ref:
                raise ValueError("SQLite checks need a database_ref and a SELECT query")
            if not re.match(r"\s*SELECT\b", self.query, re.I) or ";" in self.query:
                raise ValueError("Only a single SELECT statement is allowed")
        return self


def origin(url):
    p = urlsplit(url)
    check_target(url, resolve=False)
    if p.username or p.password:
        raise ValueError("Approved origins cannot contain credentials, queries or fragments")
    return f"{p.scheme.lower()}://{p.hostname.lower()}:{p.port or (443 if p.scheme == 'https' else 80)}"


class Contract(Model):
    version: Literal[1] = 1
    test_environment: bool = False
    allowed_origins: list[str] = Field(default_factory=list, max_length=20)
    flows: list[Flow] = Field(default_factory=list, max_length=100)
    rules: list[Rule] = Field(default_factory=list, max_length=40)
    checks: list[BackendCheck] = Field(default_factory=list, max_length=40)
    android_permissions: "PermissionPolicy | None" = None
    android_package: str | None = Field(default=None, pattern=r'^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$')
    # Made by Android test mode (a test build or a confirmed test website): its flows may use the test-mode rules,
    # and only while that run is in test mode again (qa_runtime checks the live control with the same rules).
    test_mode: bool = False

    @model_validator(mode="after")
    def references(self):
        if self.test_mode and not self.test_environment:
            raise ValueError("Test-mode flows belong to an approved test environment")
        origins = {origin(url) for url in self.allowed_origins}
        for flow in self.flows:
            for step in flow.steps:
                if step.action == "open" and origins and origin(step.value) not in origins:
                    raise ValueError("Every page a flow opens must be inside its approved origins")
        if any(is_metadata_host(urlsplit(u).hostname, resolve=False) for u in self.allowed_origins):
            raise ValueError("Metadata services are never approved targets")
        ids = [x.id for x in [*self.flows, *self.rules, *self.checks]]
        if len(ids) != len(set(ids)):
            raise ValueError("Flow, rule and backend-check IDs must be unique")
        flow_ids = {f.id for f in self.flows}
        for item in [*self.flows, *self.rules, *self.checks]:
            if item.setup_flow and item.setup_flow not in flow_ids:
                raise ValueError("Unknown setup_flow")
        by_id = {f.id: f for f in self.flows}
        for flow in self.flows:
            visited, cursor, budget = set(), flow, 0
            while cursor:
                if cursor.id in visited:
                    raise ValueError('Setup flows cannot contain a cycle')
                visited.add(cursor.id)
                budget += cursor.timeout_s
                if len(visited) > 5 or budget > 600:
                    raise ValueError('Setup chains are limited to five flows and 600 seconds')
                cursor = by_id.get(cursor.setup_flow)
            permissions = {s.permission for s in flow.steps if s.permission} | {p for s in flow.steps for p in s.permissions or []}
            if permissions and flow.approved and self.test_environment and (self.android_permissions is None or not self.android_permissions.approved
                                or not permissions <= set(self.android_permissions.allowed)):
                raise ValueError('Permission tests require an approved emulator permission policy listing every requested permission')
        for check in self.checks:
            if check.kind == "http" and origin(check.url) not in origins:
                raise ValueError("Every API URL needs an explicitly approved origin")
        for flow in self.flows:
            if any(s.action == "context" and s.value == "webview" for s in flow.steps) and not origins:
                raise ValueError("WebView flows need explicitly approved origins")
        return self


def parse_contract(value=None):
    if isinstance(value, str):
        if len(value) > 64000:
            raise ValueError("The QA contract must be no larger than 64 KB")
        value = json.loads(value) if value.strip() else {}
    if isinstance(value, Contract):
        value = value.model_dump(mode="json")
    test_mode = isinstance(value, dict) and value.get("test_mode") is True
    try:
        return Contract.model_validate(value or {}, context={"test_mode": test_mode})
    except ValidationError as error:
        messages = [
            ".".join(map(str, e["loc"])) + ": " + e["msg"] for e in error.errors(include_input=False, include_url=False)
        ]
        raise ValueError("; ".join(messages)[:1000]) from None


def finite_decimal(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Expected a finite decimal number") from error
    if not number.is_finite() or abs(number) > Decimal("1e15"):
        raise ValueError("Expected a bounded finite decimal number")
    return number


def displayed_number(text):
    matches = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", text)
    if len(matches) != 1:
        raise ValueError("A numeric locator must identify text containing exactly one number")
    return finite_decimal(matches[0].replace(",", ""))


def evaluate(expression, variables, validate_only=False):
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise ValueError("Invalid business expression") from None
    if len(list(ast.walk(tree))) > 60:
        raise ValueError("Business expression is too complex")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float, str):
            return finite_decimal(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = visit(node.left), visit(node.right)
            if validate_only:
                return Decimal(1)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("Only numbers, declared variables and + - * / are allowed")

    return finite_decimal(visit(tree))


def flow_chain(contract, flow_id):
    by_id = {flow.id: flow for flow in contract.flows}
    while flow_id:
        flow = by_id[flow_id]
        yield flow
        flow_id = flow.setup_flow


def contract_case_budget(contract, contract_id):
    if any(f.id == contract_id for f in contract.flows):
        return sum(f.timeout_s for f in flow_chain(contract, contract_id))
    item = next((i for i in [*contract.rules, *contract.checks] if i.id == contract_id), None)
    setup = sum(f.timeout_s for f in flow_chain(contract, item.setup_flow)) if item and item.setup_flow else 0
    return min(600, max(90, setup + 30))


def contract_cases(contract):
    result = []
    for kind, items in (("flow", contract.flows), ("rule", contract.rules), ("backend", contract.checks)):
        for item in items:
            approved = contract.test_environment and (kind != "flow" or item.approved)
            if getattr(item, "setup_flow", None):
                approved = approved and all(f.approved for f in flow_chain(contract, item.setup_flow))
            if kind == "flow":
                expected = "; ".join(step.action + (" = " + step.value if step.value is not None else "") for step in item.steps if step.action.startswith("assert_"))
            elif kind == "rule":
                expected = "Displayed number = " + item.expression + " (tolerance " + item.tolerance + ")"
            else:
                expected = ("HTTP " + str(item.status) + " " + item.json_pointer if item.kind == "http" else "Read-only database scalar") + " = " + repr(item.expected)
            result.append(
                {
                    "id": "contract_" + item.id,
                    "contract_id": item.id,
                    "title": item.title,
                    "kind": "contract",
                    "category": kind,
                    "type": "workflow",
                    "element_ids": [],
                    "expected": expected,
                    "requirement": "User-supplied QA contract",
                    "generation_source": "contract",
                    "blocked": not approved,
                    "automation_note": "Approve this flow and its test environment before execution."
                    if not approved
                    else "",
                    "functionality_status": "confirmed" if approved else "blocked",
                    "authentication": kind == "flow" and any(f.authentication for f in flow_chain(contract, item.id)),
                    "plan": [["assert_contract", [item.id]]] if approved else [],
                    # Explicit contracts are the business-outcome oracle (web + Android).
                    "verification": "business" if approved else "interaction",
                }
            )
    return result


def write_authorization_gap(*, environment: str, writes_ok: bool, allow_actions: list[str] | None = None,
                            action_class: str = "write") -> str:
    """Why a write / consequential workflow stays blocked — never auto-enabled by environment=test alone.

    Returns '' when the existing authorization settings already permit the action class on staging with writes_ok.
    """
    from .actions import permission_needed

    allow_actions = list(allow_actions or [])
    if environment != "staging" or not writes_ok:
        return (f"Write/business mutation blocked: missing {permission_needed(action_class)}. "
                "environment=test (or production) never enables writes by itself.")
    if action_class in ("delete", "logout", "password") and action_class not in allow_actions:
        return f"Write blocked: missing permission — {permission_needed(action_class)}"
    if action_class == "pay" and ("pay" not in allow_actions):
        return f"Write blocked: missing permission — {permission_needed('pay')}"
    return ""


def business_outcome_requires_oracle(case: dict, *, has_requirements: bool = False,
                                     has_contract: bool = False) -> str:
    """Empty when the case may claim a business outcome; otherwise the precise missing oracle/permission.

    Authorized read-only search/filter/pagination/sort cases that already assert defined outcomes are allowed.
    Unsubmitted form / input-only checks stay interaction. Writes need staging + writes_ok + unique data + cleanup
    elsewhere; this helper only names the missing outcome oracle.
    """
    from .assert_strength import verification_credit

    credit = verification_credit(case)
    if credit == "business":
        return ""
    if credit == "smoke":
        return "Smoke/page-load check only — not a business outcome"
    kind = case.get("kind") or case.get("journey") or ""
    if kind in ("form",) or case.get("journey") == "form":
        if has_requirements or has_contract:
            return ""
        return ("Unsubmitted form / input-only check: values may be retained, but Save/create/update/search "
                "persistence needs an explicit requirement or QA contract (and write authorization for sends)")
    if has_requirements or has_contract:
        return ""
    return "Business outcome needs an explicit requirement or QA contract"
