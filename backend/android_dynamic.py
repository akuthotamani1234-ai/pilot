"""One recovery path for Android Chrome and native apps.

A wait ends when visible content is stable, or when its ceiling is reached. It does not wait for a shop's ads or
analytics to go quiet. A popup is dismissed only by an exact safe label, or by one approved contract choice.
A stale or covered control is tried once more. The same control on the same screen is not tried again after that.
"""
import json
import re
from pathlib import Path

from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException

from .qa_contracts import protected

SAFE_DISMISS = frozenset({
    "close", "dismiss", "skip", "not now", "maybe later", "no thanks", "cancel", "x",
})
BLOCKED_DYNAMIC = "Blocked: screen is changing or covered by dynamic UI."
SETTLE_NOTE = "Waiting for the page to settle"
BLANK_NOTE = "The page has no visible content yet"
SECURITY_NOTE = "A security check needs you on the device"
RETRY_NOTE = "Retrying after the control changed"
OVERLAY_BLOCKED = "Blocked by an unresolved popup"
DISMISSED_NOTE = "Safe overlay dismissed"
CHOICE_NOTE = "Required approved choice applied"
LOW_CONFIDENCE = "A low-confidence locator cannot change data unless the QA contract names this control."
PRODUCTION_WRITE = (
    "This changes data. On a production app the run only opens home, categories, search, and product pages. "
    "Cart, login, and other changes need test-build confirmation and an approved contract."
)
SAFETY_RESTRICTIONS = (
    "Checkout, payment, and placing an order are never tested.",
    "A production run may open home, categories, search, and a product. Cart, login, and other changes need test-build confirmation and an approved contract.",
    "A structural locator cannot change data unless the QA contract names that control.",
    "A security check pauses for the person on the device. It is not treated as the shop, and it is not waited on for hours.",
)

PRICE = re.compile(r"(?:[$€£₹]\s*)?\d{1,3}(?:[, ]\d{3})*(?:\.\d{2})|\b\d+\.\d{2}\b")
AD_ID = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
CLOCK = re.compile(r"\b(?:today|yesterday|\d{1,2}:\d{2}(?::\d{2})?|\d{4}-\d{2}-\d{2})\b", re.I)
SECURITY = re.compile(
    r"just a moment|attention required|verify you are human|security check|are you a robot|"
    r"checking your browser|cloudflare|captcha|turnstile",
    re.I,
)
DATA_CHANGE = re.compile(
    r"\b(?:add to (?:cart|bag|basket)|remove from (?:cart|bag|basket)|update (?:cart|bag|basket)|"
    r"log ?in|sign ?in|sign ?up|register|create account|submit|save(?: changes)?|apply coupon)\b",
    re.I,
)
OVERLAY_REJECT = re.compile(
    r"\b(?:pay|payment|purchase|buy|checkout|place ?order|delete|remove account|permission|password|"
    r"subscribe|share|install|account)\b",
    re.I,
)
CAROUSEL = re.compile(r"pager|carousel|banner|slider", re.I)
_last_note = None
_progress_path: Path | None = None


def set_progress_log(path) -> None:
    """Keep the plain progress lines in the run folder, so a stopped run can be read from files."""
    global _progress_path
    _progress_path = Path(path) if path else None


def note(message: str) -> None:
    """Print one plain progress line. Repeating the same line adds nothing."""
    global _last_note
    text = " ".join(str(message or "").split())
    if not text or text == _last_note:
        return
    _last_note = text
    print("::note::" + text, flush=True)
    if _progress_path is not None:
        from .finalization import append_text_unless_linked
        append_text_unless_linked(_progress_path, text + "\n")


def reset_notes() -> None:
    global _last_note
    _last_note = None


def exact_label(text: str) -> str:
    label = " ".join(str(text or "").replace("×", "x").replace("✕", "x").replace("✗", "x").split())
    return label.casefold()


def is_exact_safe_dismiss(text: str) -> bool:
    """True only for the whole label. 'Cancel order' and 'Close account' are not dismissals."""
    return exact_label(text) in SAFE_DISMISS


def overlay_target_rejected(text: str) -> str:
    """Why an approved popup choice is refused. Empty when the target is allowed."""
    label = " ".join(str(text or "").split())
    if not label:
        return "The approved popup choice has no target."
    if protected(label) or OVERLAY_REJECT.search(label):
        return "The approved popup choice looks like payment, purchase, delete, permission, or an account action."
    return ""


def locator_confidence(locator: dict | None) -> str:
    """high for a resource id, accessibility id, or unique text. low for a structural selector."""
    if not isinstance(locator, dict):
        return "low"
    strategy = locator.get("strategy") or ""
    value = str(locator.get("value") or "")
    if strategy in {"resource_id", "accessibility_id", "text"} and value:
        return "high"
    if strategy == "css":
        if ":nth-of-type" in value or ":nth-child" in value:
            return "low"
        if value.startswith("#") or "[name=" in value or "aria-label" in value:
            return "high"
        if "href=" in value or "[placeholder=" in value or value.startswith("[data-"):
            return "medium"
        return "medium" if value else "low"
    return "low"


def is_data_change(text: str) -> bool:
    return bool(DATA_CHANGE.search(" ".join(str(text or "").split())))


def contract_names(contract, label: str) -> bool:
    """An approved tap names the control when its locator is the control's exact text, id, or description."""
    wanted = exact_label(label)
    if not wanted:
        return False
    flows = getattr(contract, "flows", None)
    if flows is None and isinstance(contract, dict):
        flows = contract.get("flows") or []
    for flow in flows or []:
        approved = flow.get("approved") if isinstance(flow, dict) else getattr(flow, "approved", False)
        if not approved:
            continue
        steps = flow.get("steps") if isinstance(flow, dict) else flow.steps
        for step in steps or []:
            action = step.get("action") if isinstance(step, dict) else step.action
            locator = step.get("locator") if isinstance(step, dict) else step.locator
            if action != "tap" or locator is None:
                continue
            strategy = locator.get("strategy") if isinstance(locator, dict) else locator.strategy
            value = locator.get("value") if isinstance(locator, dict) else locator.value
            if strategy in {"text", "resource_id", "accessibility_id"} and exact_label(value) == wanted:
                return True
    return False


def data_change_blocked(label: str, *, test_build: bool, locator: dict | None, contract=None) -> str:
    """Empty when this control may be used. Production writes and weak locators stay blocked."""
    if not is_data_change(label):
        return ""
    if not test_build:
        return PRODUCTION_WRITE
    if locator_confidence(locator) == "low" and not contract_names(contract, label):
        return LOW_CONFIDENCE
    return ""


def has_visible_content(screen: dict | None) -> bool:
    if not isinstance(screen, dict) or screen.get("loading"):
        return False
    for element in screen.get("elements") or []:
        if element.get("visible", True) is False:
            continue
        if element.get("text") or element.get("accessibility_id") or element.get("clickable"):
            return True
    return False


def security_reason(screen: dict | None) -> str:
    """A check for a person. It is not the shop, and the caller must stop at its own ceiling."""
    if not isinstance(screen, dict):
        return ""
    name = str(screen.get("screen_name") or "")
    texts = [str(element.get("text") or "") for element in screen.get("elements") or [] if element.get("visible", True)]
    if SECURITY.search(name) or (SECURITY.search(name + " " + " ".join(texts[:8])) and len(texts) <= 8):
        return SECURITY_NOTE
    return ""


def _popup(screen: dict) -> bool:
    identity = screen.get("identity") or []
    if identity[:1] == ["dialog"]:
        return True
    for element in screen.get("elements") or []:
        if element.get("visible", True) is False:
            continue
        resource = element.get("resource_id") or ""
        if resource in {"android:id/alertTitle", "android:id/parentPanel"} or element.get("region") == "dialog":
            return True
    return False


def _calm(text: str, keep: bool = False) -> str:
    raw = " ".join(str(text or "").split())
    if keep:
        return raw[:160]
    raw = PRICE.sub("#", raw)
    raw = AD_ID.sub("#", raw)
    raw = CLOCK.sub("#", raw)
    return raw[:160]


def stable_fingerprint(screen: dict) -> str:
    """Ignore flickering prices, ad ids, and carousel text. Keep a popup in the signature."""
    popup = _popup(screen)
    parts = []
    if popup:
        overlay_text = " ".join(
            str(element.get("text") or element.get("accessibility_id") or "")
            for element in screen.get("elements") or []
            if element.get("visible", True) is not False and (
                element.get("region") == "dialog"
                or str(element.get("resource_id") or "").startswith("android:id/")
                or (screen.get("identity") or [None])[0] == "dialog"
            )
        )
        parts.append(["popup", _calm(overlay_text, keep=True)])
    for element in screen.get("elements") or []:
        if element.get("visible", True) is False:
            continue
        described = " ".join((
            element.get("class_name") or "", element.get("resource_id") or "", element.get("accessibility_id") or "",
        ))
        if CAROUSEL.search(described) and element.get("region") != "dialog":
            parts.append(["carousel", element.get("class_name") or "", element.get("resource_id") or ""])
            continue
        parts.append([
            element.get("class_name") or "",
            element.get("resource_id") or "",
            _calm(element.get("accessibility_id") or ""),
            _calm(element.get("text") or ""),
        ])
    route = str(screen.get("web_url") or screen.get("activity") or "")
    payload = {"route": route.split("?", 1)[0], "popup": popup, "parts": parts}
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def frame_key(screen: dict) -> str:
    return str(screen.get("stable_fingerprint") or screen.get("fingerprint") or "")


def _visible_labels(screen: dict) -> list[dict]:
    labels = []
    for element in screen.get("elements") or []:
        if element.get("visible", True) is False or not element.get("clickable", True):
            continue
        text = element.get("text") or element.get("accessibility_id") or ""
        if text:
            labels.append(element)
    return labels


def _overlay_text(screen: dict) -> str:
    chunks = []
    for element in screen.get("elements") or []:
        if element.get("visible", True) is False:
            continue
        if element.get("region") == "dialog" or (screen.get("identity") or [None])[0] == "dialog":
            text = element.get("text") or element.get("accessibility_id") or ""
            if text:
                chunks.append(str(text))
    return " ".join(chunks)[:500]


def _choices(contract) -> list:
    choices = getattr(contract, "overlay_choices", None)
    if choices is None and isinstance(contract, dict):
        choices = (contract.get("overlay_choices") or [])
    return list(choices or [])


def plan_overlay(screen: dict | None, contract=None) -> dict:
    """none, dismiss, choice, or blocked. A choice that looks protected is refused."""
    screen = screen or {}
    if not _popup(screen):
        return {"action": "none", "message": "", "target_text": "", "overlay_text": ""}
    overlay_text = _overlay_text(screen)
    labels = _visible_labels(screen)
    visible = {
        exact_label(element.get("text") or element.get("accessibility_id") or "")
        for element in screen.get("elements") or []
        if element.get("visible", True) is not False
    }
    for choice in _choices(contract):
        match = choice.get("match_text") if isinstance(choice, dict) else choice.match_text
        target = choice.get("target_text") if isinstance(choice, dict) else choice.target_text
        if exact_label(match) and exact_label(match) in visible:
            rejected = overlay_target_rejected(target)
            if rejected:
                return {"action": "blocked", "message": OVERLAY_BLOCKED + " " + rejected,
                        "target_text": "", "overlay_text": overlay_text, "reason": rejected}
            if any(exact_label(element.get("text") or element.get("accessibility_id") or "") == exact_label(target)
                   for element in labels):
                return {"action": "choice", "message": CHOICE_NOTE, "target_text": str(target),
                        "overlay_text": overlay_text}
    safe = [element for element in labels if is_exact_safe_dismiss(element.get("text") or element.get("accessibility_id") or "")]
    if len(safe) == 1:
        target = safe[0].get("text") or safe[0].get("accessibility_id") or ""
        return {"action": "dismiss", "message": DISMISSED_NOTE, "target_text": str(target), "overlay_text": overlay_text}
    return {
        "action": "blocked",
        "message": OVERLAY_BLOCKED,
        "target_text": "",
        "overlay_text": overlay_text,
        "reason": OVERLAY_BLOCKED,
    }


def control_key(element) -> str:
    if element is None:
        return ""
    if isinstance(element, dict):
        locator = (element.get("locators") or [{}])[0]
        return exact_label(element.get("text") or element.get("accessibility_id") or element.get("resource_id") or locator.get("value") or "")
    # A live control can already be stale or sitting under an alert. Its Python identity is enough,
    # and reading its text would turn a successful tap into a failure.
    return str(id(element))


class ActionRecovery:
    """Remembers one retry and one failure for each control on one stable screen."""

    def __init__(self, retries: int = 1):
        # One retry is the ceiling. Zero means a stale or covered control is not tried again.
        self.retry_limit = 1 if int(retries) >= 1 else 0
        self.retries: dict[tuple, int] = {}
        self.failures: dict[tuple, int] = {}
        self.events: list[dict] = []

    def _key(self, screen, element) -> tuple:
        screen = screen or {}
        return (frame_key(screen), control_key(element))

    def exhausted(self, screen, element) -> bool:
        return self.failures.get(self._key(screen, element), 0) >= 1

    def allow_retry(self, screen, element) -> bool:
        key = self._key(screen, element)
        if self.retries.get(key, 0) >= self.retry_limit:
            return False
        self.retries[key] = 1
        return True

    def fail(self, screen, element) -> None:
        key = self._key(screen, element)
        self.failures[key] = self.failures.get(key, 0) + 1

    def record(self, run_dir, event: dict, screenshot: str | None = None, retries: int = 0) -> None:
        stored = {
            "kind": event.get("action") or "note",
            "message": str(event.get("message") or "")[:300],
            "overlay_text": str(event.get("overlay_text") or "")[:500],
            "locator_type": str(event.get("locator_type") or ""),
            "locator_confidence": str(event.get("locator_confidence") or ""),
            "retries": int(retries),
            "blocked_reason": str(event.get("reason") or event.get("message") or "")[:300],
            "screenshot": screenshot or "",
        }
        self.events.append(stored)
        if run_dir:
            from .finalization import write_text_unless_linked
            from .safety import redact_data

            write_text_unless_linked(Path(run_dir), "dynamic.json", json.dumps(redact_data({"events": self.events}), indent=2))


def perform_tap(element, *, click, refind, recovery: ActionRecovery, screen=None, contract=None,
                run_dir=None, shoot=None, press_label=None, inspect=None):
    """Tap once. If the control is stale or covered, handle one popup, find it again, and tap once more."""
    screen = screen or {}
    target = element
    if recovery.exhausted(screen, target):
        note(BLOCKED_DYNAMIC)
        raise RuntimeError(BLOCKED_DYNAMIC)
    locator = (element.get("locators") or [{}])[0] if isinstance(element, dict) else {}
    event = {
        "action": "tapped",
        "message": "Control tapped",
        "locator_type": locator.get("strategy", ""),
        "locator_confidence": locator_confidence(locator) if locator else "",
    }

    def fail(plan):
        shot = shoot("overlay-blocked") if shoot else None
        blocked = {"action": "blocked", "message": plan.get("message") or BLOCKED_DYNAMIC,
                   "reason": plan.get("reason") or plan.get("message") or BLOCKED_DYNAMIC,
                   "overlay_text": plan.get("overlay_text", ""), "locator_type": event["locator_type"],
                   "locator_confidence": event["locator_confidence"]}
        recovery.record(run_dir, blocked, screenshot=shot, retries=recovery.retries.get(recovery._key(screen, target), 0))
        recovery.fail(screen, target)
        note(blocked["message"])
        raise RuntimeError(blocked["message"])

    while True:
        try:
            click(element)
            recovery.record(run_dir, event, retries=recovery.retries.get(recovery._key(screen, target), 0))
            return element
        except (StaleElementReferenceException, ElementClickInterceptedException):
            if not recovery.allow_retry(screen, target):
                fail({"message": BLOCKED_DYNAMIC, "reason": BLOCKED_DYNAMIC})
            note(RETRY_NOTE)
            if inspect is not None:
                screen = inspect() or screen
            plan = plan_overlay(screen, contract)
            if plan["action"] == "blocked":
                fail(plan)
            if plan["action"] in {"dismiss", "choice"}:
                if press_label is None:
                    fail({"message": OVERLAY_BLOCKED, "reason": OVERLAY_BLOCKED, "overlay_text": plan.get("overlay_text", "")})
                press_label(plan["target_text"])
                recovery.record(run_dir, plan)
                note(plan["message"])
            element = refind()
            if element is None:
                fail({"message": "The control is not on the screen.", "reason": "The control is not on the screen."})


def scroll_stalled(previous_total, total, stalls: int, limit: int) -> tuple[int, bool]:
    """Count scrolls that added no content. Stop when the count reaches the ceiling."""
    if previous_total is not None and total == previous_total:
        stalls += 1
        return stalls, stalls >= max(1, limit)
    return 0, False


def dynamic_summary(events: list[dict]) -> dict:
    dismissed = sum(event.get("kind") == "dismiss" for event in events)
    choices = sum(event.get("kind") == "choice" for event in events)
    detected = sum(event.get("kind") in {"dismiss", "choice", "blocked"} and event.get("overlay_text") for event in events)
    retries = sum(int(event.get("retries") or 0) for event in events)
    blocked = [event.get("blocked_reason") for event in events if event.get("kind") == "blocked" and event.get("blocked_reason")]
    return {
        "overlays_detected": detected,
        "overlays_dismissed": dismissed,
        "choices_applied": choices,
        "retries": retries,
        "blocked_reasons": blocked,
        "events": events,
        "safety_restrictions": list(SAFETY_RESTRICTIONS),
    }
