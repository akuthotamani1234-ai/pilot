"""Which clicks are allowed? Every button / link text is put in a class before anything is clicked:

  safe          look, navigate, search, filter, sort, next page, tabs, menus, close a popup
  test_account  reversible changes to the TEST account only: add to cart / wishlist, quantity, choose an option
  write         sends or saves data: submit, save, update, send, post, publish, upload, create, subscribe, invite ...
  delete        delete, remove, deactivate, cancel an account / order / subscription
  pay           pay, buy, purchase, checkout, place an order, confirm a payment, transfer, donate, book
  logout        log out / sign out
  password      change password / e-mail, reset password

What the run may do depends on its environment (TEST_ENVIRONMENT, the UI's advanced settings, --env):
  production   safe (+ nothing that changes data: the consequential classes are 'protected', never clicked, reported
               as "Blocked - needs approval"; forms are checked without being sent)
  test         (the default) as production for data - plus reversible test-account actions (cart, wishlist) and the
               empty-form check. The default never sends data: a public site tested without choosing stays untouched.
  staging      the owner's test copy: + write (the form tests send valid and wrong data; create -> find -> edit ->
               delete, with tagged test data, cleaned up after) + delete / logout / password only when named in
               ALLOW_ACTIONS; pay only with ALLOW_ACTIONS=pay AND TEST_PAYMENT=1. On a host that does not look like a
               test copy (no staging / test / qa / dev / uat / preview / sandbox / localhost in it) only after the
               second confirmation (CONFIRM_WRITES=1, the UI's tick, --confirm-writes).
An allowed consequential action is 'write' for the callers: never done by exploring - only by the tests made for it.
"""
import re

from .config import settings

# Payment *intent* only (checkout / pay now / place order / confirm payment / buy).
# Admin nav like "Pay Grades", "Payment Methods", bare "Confirm", HR "Transfer Employee" are carved out in
# action_class via nav-aware helpers — not every word containing pay/transfer/confirm.
PAY = re.compile(
    r"\bpay\s*now\b|\bpay\b(?![\s_-]*(grades?|methods?|grade|period|scale)\b)|"
    r"\bpayments?\b(?![\s_-]*methods?\b)|billing|"
    r"\bbuy\b|\bpurchase\b|check[\s-]?out|place (your )?order|order now|"
    r"confirm (order|purchase|payment)\b|send money|"
    r"\bdonate\b(?!\s+(blood|organ|time)\b)|book now|reserve now",
    re.I,
)
# Labels that look like pay keywords but are admin/nav config (not checkout submits).
ADMIN_PAY_NAV = re.compile(
    r"^\s*(pay[\s_-]*grades?|payment[\s_-]*methods?|pay[\s_-]*periods?|pay[\s_-]*scales?)\s*$",
    re.I,
)
BARE_CONFIRM = re.compile(r"^\s*confirm\s*$", re.I)
HR_TRANSFER = re.compile(r"^\s*transfer(\s+\w+){0,3}\s*$", re.I)
LOGOUT = re.compile(r"log ?out|sign ?out|log ?off", re.I)
PASSWORD = re.compile(r"change (my )?(password|email)|reset password", re.I)
# (\btrash: a button that only shows a trash-can icon - 'bi trash', 'fa trash alt' - deletes)
DELETE = re.compile(r"delete|remove|\btrash|unsubscribe|deactivate|close (my )?account|"
                    r"cancel (my )?(account|subscription|order|booking)", re.I)
WRITE = re.compile(r"\bsend\b|\bpost\b|publish|\bshare\b|\binvite\b|\bsave\b|submit|\bupdate\b|apply changes|\bapprove|"
                   r"\breject|\bassign|\bupload\b|\bimport\b|\bsubscribe\b", re.I)
CLASSES = (("pay", PAY), ("logout", LOGOUT), ("password", PASSWORD), ("delete", DELETE), ("write", WRITE))
# every consequential word (the static union - for code that only needs yes / no, and for the tests that must never
# press such a control in passing: only the tests made for it may)
PROTECTED = re.compile("|".join(rx.pattern for _, rx in CLASSES), re.I)
# (taking an item out of the test's OWN cart is as reversible as putting it in: the cart line's remove control -
# automationexercise.com's a.cart_quantity_delete - is no 'delete' of data. Checkout / pay stay protected)
TEST_ACCOUNT = re.compile(
    r"add to (cart|basket|bag|trolley)|add to (wish ?list|list|favou?rites)|wish ?list|save for later|"
    r"\bquantity\b|^\s*[+\-–−]\s*$|increase|decrease|select (size|colou?r|option)|"
    r"(cart|basket|trolley)[\w-]*(delete|remove)|(delete|remove)[\w-]*(cart|basket|trolley)|"
    r"remove (this |the )?(item |product )?from (the |your |my )?(cart|basket|bag|trolley)", re.I)

UNSAFE_BUTTON = PROTECTED

# what the button SAYS decides first: 'Search' with id="search-submit" only searches, 'Log in' only logs in
SAFE_TEXT = re.compile(r"^\s*(search|find|go|filter|apply filters?|sort|log ?in|sign ?in|next|previous|show more|"
                       r"load more|view|open|close)\s*$", re.I)
# a button without words whose ICON says search ('fa fa-search', 'bi-search', a magnifier) only searches - its code name
# (automationexercise.com: id="submit_search") must not make it a 'submit' that is never pressed
SEARCH_ICON = re.compile(r"\bsearch\b|magnif", re.I)
REFERENCE_NAV = re.compile(r"^\s*(?:pay|payment|salary|compensation|billing)\s+"
                           r"(?:grades?|bands?|types?|methods?|settings|configuration|history|reports?|categories|policies)\s*$", re.I)


def reference_navigation(text: str, context: dict | None = None) -> bool:
    """A reference/configuration destination, identified by purpose and native navigation context."""
    context = context or {}
    href = context.get("href") or ""
    if not REFERENCE_NAV.fullmatch(text or "") or context.get("tag") != "a" or context.get("in_form"):
        return False
    if re.search(r"javascript:|/(?:pay|checkout|purchase|transfer|confirm|delete|logout)(?:/|$)|"
                 r"[?&](?:action|do|cmd)=(?:pay|buy|delete|transfer|confirm)", href, re.I):
        return False
    return context.get("role") == "menuitem" or bool(href and href != "#")

# Back-compat alias used by tests / callers.
PAY_GRADE_LABEL = ADMIN_PAY_NAV
NAV_ROLES = frozenset({
    "link", "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "navigation", "menu", "treeitem",
})
NAV_KINDS = frozenset({
    "link", "menu", "menu_item", "tab", "tabs", "navigation", "sidebar", "tree_item", "hover",
})
NAV_TAGS = frozenset({"a", "nav"})
NAV_PURPOSES = frozenset({"navigate", "navigation", "menu", "tab", "link", "open_page", "admin_config"})


def _kind_of(s: str) -> str:
    return next((name for name, rx in CLASSES if rx.search(s or "")), "")


def _nav_context(*, role: str | None = None, kind: str | None = None, tag: str | None = None,
                 purpose: str | None = None, href: str | None = None, selector: str | None = "") -> bool:
    """True when the control looks like navigation (link / menu / tab), not a pay/checkout submit."""
    if re.search(r"javascript:|/(?:pay|checkout|purchase|transfer|confirm|delete|logout)(?:/|$)|"
                 r"[?&](?:action|do|cmd)=(?:pay|buy|delete|transfer|confirm)", href or "", re.I):
        return False
    role_l = (role or "").strip().lower()
    kind_l = (kind or "").strip().lower()
    tag_l = (tag or "").strip().lower()
    purpose_l = (purpose or "").strip().lower()
    if role_l in NAV_ROLES or kind_l in NAV_KINDS or tag_l in NAV_TAGS or purpose_l in NAV_PURPOSES:
        return True
    href_l = (href or "").strip()
    if href_l and not href_l.startswith("#") and not href_l.lower().startswith("javascript:"):
        return True
    sel = selector or ""
    if re.search(r"(^|[\s\[>#.])a([\s\[.#:]|$)|role=['\"]?(link|menuitem|tab)\b", sel, re.I):
        return True
    return False


def is_pay_grade_navigation(text: str | None, selector: str | None = "", *,
                            role: str | None = None, kind: str | None = None, tag: str | None = None,
                            purpose: str | None = None, href: str | None = None) -> bool:
    """Link/menuitem/tab to admin pay-config pages (Pay Grades / Payment Methods / …) is not payment."""
    label = (text or "").split("\n")[0].strip()
    if not ADMIN_PAY_NAV.match(label):
        return False
    return _nav_context(role=role, kind=kind, tag=tag, purpose=purpose, href=href, selector=selector)


def is_safe_admin_nav(text: str | None, selector: str | None = "", *,
                      role: str | None = None, kind: str | None = None, tag: str | None = None,
                      purpose: str | None = None, href: str | None = None) -> bool:
    """Nav that must never be treated as checkout/payment: pay-config, bare Confirm, HR Transfer…"""
    label = (text or "").split("\n")[0].strip()
    if not label:
        return False
    if not _nav_context(role=role, kind=kind, tag=tag, purpose=purpose, href=href, selector=selector):
        return False
    if ADMIN_PAY_NAV.match(label) or BARE_CONFIRM.match(label) or HR_TRANSFER.match(label):
        return True
    return False


def action_class(text: str | None, selector: str | None = "", context: dict | None = None, *,
                 role: str | None = None, kind: str | None = None, tag: str | None = None,
                 purpose: str | None = None, href: str | None = None) -> str:
    """'safe' | 'test_account' | 'write' | 'delete' | 'pay' | 'logout' | 'password' - what the control would do."""
    if context:
        role, kind, tag = role or context.get("role"), kind or context.get("kind"), tag or context.get("tag")
        purpose, href = purpose or context.get("purpose"), href or context.get("href")
    in_form = bool((context or {}).get("in_form"))
    if not in_form and is_safe_admin_nav(text, selector, role=role, kind=kind, tag=tag, purpose=purpose, href=href):
        return "safe"
    if not in_form and is_pay_grade_navigation(text, selector, role=role, kind=kind, tag=tag, purpose=purpose, href=href):
        return "safe"
    t = f"{text or ''} {selector or ''}"
    if reference_navigation(text or "", context):
        return "safe"
    if ADMIN_PAY_NAV.fullmatch(text or "") or REFERENCE_NAV.fullmatch(text or ""):
        return "pay"
    if TEST_ACCOUNT.search(t) and not PAY.search(t):
        return "test_account"
    by_text = _kind_of(text or "")
    if by_text:
        return by_text
    if SAFE_TEXT.search(text or "") or SEARCH_ICON.search(text or ""):
        return "safe"
    return _kind_of(selector or "") or "safe"  # no telling text: the code's name (id="delete-account") decides


def writes_allowed() -> bool:
    """May this run change data (send forms, create / edit / delete records)? Staging, confirmed for its host."""
    return settings.environment == "staging" and settings.writes_ok


def allowed(kind: str) -> bool:
    """May this run perform an action of this class (only through the tests made for it)?"""
    if kind in ("safe", "test_account"):
        return True
    if not writes_allowed():
        return False
    if kind == "write":
        return True
    if kind == "pay":
        return "pay" in settings.allow_actions and settings.test_payment
    return kind in settings.allow_actions


def permission_needed(kind: str) -> str:
    """Which setting would allow this consequential class (for blocked-reason text)."""
    if kind == "pay":
        return "ALLOW_ACTIONS including 'pay' and TEST_PAYMENT=1 (staging only)"
    if kind in ("delete", "logout", "password"):
        return f"ALLOW_ACTIONS including '{kind}' (staging only)"
    if kind == "write":
        return "TEST_ENVIRONMENT=staging with write confirmation for the host"
    return "explicit approval for this action class"


def blocked_reason(kind: str) -> str:
    """Why a protected control was not clicked, and which permission would be needed."""
    if kind == "pay":
        return (f"protected: payment/checkout/billing submit - never performed without "
                f"{permission_needed('pay')}")
    if kind in ("delete", "logout", "password", "write"):
        return (f"protected: '{kind}' action - never performed without {permission_needed(kind)}")
    return ("protected: it could pay, order, delete, send, publish or log out - never performed without "
            "ALLOW_ACTIONS naming the class (and TEST_PAYMENT=1 for pay)")


def action_risk(text: str | None, selector: str | None = "", context: dict | None = None, *,
                role: str | None = None, kind: str | None = None, tag: str | None = None,
                purpose: str | None = None, href: str | None = None) -> str:
    """'safe' | 'test_account' | 'write' (allowed here: only the tests made for it do it) | 'protected' (never)."""
    cls = action_class(text, selector, context, role=role, kind=kind, tag=tag, purpose=purpose, href=href)
    if cls in ("safe", "test_account"):
        return cls
    return "write" if allowed(cls) else "protected"


def protected_pattern() -> str:
    """The words of every class this run may NOT perform (the generated tests' runtime guard, conftest.py)."""
    return "|".join(rx.pattern for name, rx in CLASSES if not allowed(name)) or r"(?!x)x"
