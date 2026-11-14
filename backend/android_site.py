"""Test mode for a test / demo WEBSITE in Android Chrome: use everything a real user can, except checkout.

The person ticked the test-mode box, confirming the website is a test or demo site they may test. On top of the shared
core (android_interact.Session: fresh state, replay before a test is kept, the coverage list) this explorer works in
the order a manual tester does:
  1. every menu first: the phone menu button, each top-level and category entry, the footer's links inside the
     approved origin - each page must open; it is recorded (screenshot, inventory) and the next check starts fresh.
     An entry that opens a dialog instead (a "Log in" / "Sign up" / "Contact" pop-up) makes a state: its boxes are
     filled and submitted in step 3 exactly like a page's form
  2. every page to its end: scrolled like a user so late-loading content appears; controls below the first screen
     are recorded with how to reach them
  3. every feature, each from a fresh state (this website's cookies and storage cleared, the start page reloaded):
     forms (sign-up, login with the account it registered or the person's test account, search, contact, newsletter,
     review, "email a friend", coupon codes), the cart (add, quantity, the cart lists the product, update, remove),
     drop-downs (sort, page size, currency), the other buttons and links (wishlist, compare, filters, a product),
     and what the login opens (account pages, log out)
Checkout, payment, placing an order, paid plans, deleting an account, sharing and calls are never pressed
(qa_contracts.never_in_test_mode); a page whose address is a checkout or payment step is never tested. Links to other
websites are listed, never followed. Every planned check ends in the coverage list: passed, failed or not tested with
a plain reason.
"""

import re
import time
from collections import Counter, deque
from urllib.parse import urlsplit

from .android import AndroidEnvironmentError
from .android_coverage import full_run
from .android_design import normalize_screens
from .android_interact import (
    SEARCH,
    SUBMIT,
    SUCCESS,
    VOLATILE,
    Budget,
    Session,
    assertion_steps,
    build_form,
    describe,
    family,
    field_kind,
    fill,
    label,
    name,
    reach,
    tap,
    usable,
)
from .qa_contracts import origin

ADD_TO_CART = re.compile(r"\badd to (?:cart|basket|bag|trolley)\b", re.I)
CART_LINK = re.compile(r"\b(shopping cart|cart|basket|bag|trolley)\b", re.I)
REMOVE = re.compile(r"\b(remove|delete|trash|bin)\b", re.I)
UPDATE = re.compile(r"\b(update|recalculate|refresh)\b", re.I)
LOGOUT = re.compile(r"\b(log ?out|sign ?out)\b", re.I)
ERROR_PAGE = re.compile(r"\b(404|page not found|not found|server error|error 50\d|an error occurred|"
                        r"something went wrong)\b", re.I)
CODE_BOX = re.compile(r"\b(coupon|discount|voucher|promo|gift ?card)\b", re.I)
# A button that only leaves the form (it does not submit the boxes before it)
NOT_SUBMIT = re.compile(r"\b(continue shopping|go shopping|keep shopping|back|cancel|close)\b", re.I)
# Addresses of checkout and payment steps (nopCommerce: /onepagecheckout): words run together, so no \b here
PROTECTED_PATH = re.compile(r"check-?out|payment|place-?order|purchase|billing|delete-?account|close-?account", re.I)
TEXT_TYPES = {"", "text", "email", "password", "tel", "url", "search", "number", "textarea", "date"}
MENU_REGIONS = ("nav", "header", "footer")
MENU_CAP, FOOTER_CAP, PRODUCT_TRIES = 40, 30, 3
PURPOSES = (("code", CODE_BOX), ("newsletter", re.compile(r"\b(newsletter|subscribe)\b", re.I)),
            ("friend", re.compile(r"\bfriend\b", re.I)), ("review", re.compile(r"\breview", re.I)),
            ("contact", re.compile(r"\b(contact|enquiry|inquiry|message)\b", re.I)))
ACTION_NAMES = {"newsletter": "Newsletter sign-up", "contact": "Contact form", "review": "Product review",
                "friend": "Email a friend", "form": "Form submission"}
ORDER = {"signup": 0, "login": 1, "search": 2, "contact": 3, "newsletter": 4, "review": 5, "friend": 6, "code": 7,
         "form": 8}


def page_key(url: str) -> str:
    """One page per address path: '?orderby=5' or '?idp_=2' shows the same page with other content."""
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc.casefold()}{parts.path.rstrip('/') or '/'}"


def pattern(element: dict) -> str:
    """The element's place without the item numbers: product cards in one list share it."""
    return re.sub(r":nth-of-type\(\d+\)", "", element.get("pos") or "")


def nm(element: dict) -> str:
    return " ".join(name(element).split())[:60]


def text_element(text: dict, selector: str) -> dict:
    """A short text the page shows, as an element a check can assert."""
    return {"id": "", "class_name": "text", "type": "text", "text": text["text"], "visible": True,
            "text_comparable": True, "locators": [{"strategy": "css", "value": selector}]}


def chain_steps(chain: list[dict]) -> list[dict]:
    return [step for element in chain for step in reach(element) + [tap(element)]]


class SiteDevice:
    """The browser for SiteSession: a fresh visit, opening a page, reading it, scrolling it, its messages."""

    def __init__(self, driver, config: dict, screens: list[dict], stop_path, deadline: float, max_tries: int,
                 record=None):
        self.driver, self.config, self.screens, self.stop_path = driver, config, screens, stop_path
        self.deadline, self.max_tries, self._record = deadline, max_tries, record

    def _check(self):
        if self.stop_path.exists():
            raise Budget("Stop requested")
        if time.monotonic() >= self.deadline:
            raise Budget("User-like testing time limit reached")

    def settle(self, timeout: float = 10) -> dict:
        from .android import inspect_driver
        from .android_runtime import settled_screen

        self._check()
        screen = settled_screen(lambda: inspect_driver(self.driver, self.config),
                                timeout=min(timeout, max(1.0, self.deadline - time.monotonic())))
        return normalize_screens([screen])[0]

    def fresh_start(self) -> dict:
        from .android_web import reset_site_data

        self._check()
        reset_site_data(self.driver, self.config)
        return self.settle(30)

    def open(self, url: str) -> dict:
        from .android_web import alert_safe, guard_url

        self._check()
        guard_url(url, self.config)
        alert_safe(self.driver, lambda: self.driver.get(url))
        return self.settle(20)

    def observe(self) -> dict:
        return self.settle(10)

    def scroll_end(self) -> int:
        from .android_web import scroll_to_end
        return scroll_to_end(self.driver, 15)

    def alerts(self, wait_s: float = 0.0) -> list[str]:
        from .android_web import collect_alerts
        return collect_alerts(self.driver, wait_s)

    def url(self) -> str:
        from .android_web import current_url
        return current_url(self.driver)

    def record(self, screen: dict) -> None:
        """A new page: screenshot, live page event and the run's screen list (the pipeline's record_screen)."""
        if self._record:
            self._record(screen)
        else:
            normalize_screens([screen])
            self.screens.append(screen)


class SiteSession(Session):
    """User-like testing of a website in Android Chrome (see the module docstring)."""

    def __init__(self, device, environment=None):
        super().__init__(device, environment)
        self.origin = origin(device.config["start_url"])
        self.max_pages = int(device.config.get("max_screens", 40)) or float("inf")
        home = self.screens[0]
        home.update(nav_steps=[], open_by_url=True, site_role="start page")
        self.pages = {page_key(home.get("web_url")): home}
        self.states: list[dict] = []
        self.entries: list[dict] = []
        self.entry_keys: set = set()
        self.toggle_queue: deque = deque()
        self.opened: dict = {}  # a menu chain -> the controls shown once it is open
        self.queue: deque = deque()
        self.read: set = set()
        self.done: set = set()
        self.form_boxes: set = set()
        self.external: dict = {}
        self.cart: dict = {}
        self.logged_in: dict | None = None

    # -------- navigation and observation
    def nav(self, screen: dict) -> list[dict]:
        return list(screen["nav_steps"]) if "nav_steps" in screen else super().nav(screen)

    def go_to(self, screen: dict, fresh: bool = True) -> dict:
        live = self.device.fresh_start()
        steps = self.nav(screen)
        if steps:
            self.perform(steps)
            live = self.device.observe()
        return live

    def observe_after(self, screen: dict, steps: list[dict], fresh: bool = True, setup: int = 0):
        """From a fresh visit: open the page, do the steps, wait for a browser message (a shop answers "Product
        added." when its request returns), then read the page. (before, None) when the browser left the website.
        The first `setup` steps (log in, fill the cart) are done before the 'before' picture: they are not the
        action's effect."""
        self.spend()
        before = self.go_to(screen)
        self.device.alerts(0)  # the start page's own messages do not belong to this action
        scrolls = setup
        while scrolls < len(steps) and steps[scrolls]["action"] == "scroll_to":
            scrolls += 1
        try:
            if scrolls:
                self.perform(steps[:scrolls])
                self.device.alerts(0.5 if setup else 0)  # the setup's own messages (an "added" alert)
                before = self.device.observe()
            self.perform(steps[scrolls:])
            moved = page_key(self.device.url()) != page_key(before.get("web_url"))
            alerts = self.device.alerts(0 if moved else 1.5)
            after = self.device.observe()
        except AndroidEnvironmentError as error:
            if "left the approved" in str(error) or "left the selected" in str(error):
                return before, None
            raise
        private = [value.casefold() for value in self.secrets.values() if value]
        after["alerts"] = [text for text in alerts if text and not any(value in text.casefold() for value in private)]
        return before, after

    def checkpoint(self):
        """Stop and time limit, for reading pages (no user-like try is spent)."""
        if self.device.stop_path.exists():
            raise Budget("Stop requested")
        if time.monotonic() >= self.device.deadline:
            raise Budget("User-like testing time limit reached")

    # -------- what changed after one action
    def diff(self, before: dict, after: dict) -> list[dict]:
        """The visible result: a browser message, the new page (title and heading), a dialog, changed or new
        texts (a cart count, a message), texts that went away, ticked boxes. Never input contents or secrets."""
        private = [value.casefold() for value in self.secrets.values() if value]

        def secret(text: str) -> bool:
            return any(value in text.casefold() for value in private)

        changes = [{"kind": "alert", "text": text[:200]} for text in after.get("alerts", [])]
        moved = page_key(after.get("web_url")) != page_key(before.get("web_url"))
        title = after.get("title") or ""
        if title and title != (before.get("title") or "") and not secret(title):
            changes.append({"kind": "title", "after": title})
        heading = self.heading(after, before)
        if heading is not None and not secret(heading.get("text", "")):
            changes.append({"kind": "appeared", "element": heading})
        if moved:
            return changes
        old_texts = before.get("texts", [])
        by_selector = {t["selector"]: t for t in old_texts}
        by_place = {t.get("pos"): t for t in old_texts if t.get("pos")}
        seen = Counter(t["text"] for t in old_texts)
        now = Counter(t["text"] for t in after.get("texts", []))
        used = {c["element"]["locators"][0]["value"] for c in changes if c.get("element")}
        for text in after.get("texts", []):
            if VOLATILE.search(text["text"]) or secret(text["text"]):
                continue
            same = by_selector.get(text["selector"]) or by_place.get(text.get("pos"))
            selector = text["selector"] if text["selector"] in by_selector or not same else text["pos"]
            if selector in used:
                continue
            if same and same["text"] != text["text"]:
                used.add(selector)
                changes.append({"kind": "text", "element": text_element(text, selector), "before": same["text"],
                                "after": text["text"]})
            elif not same and not seen[text["text"]]:
                used.add(selector)
                changes.append({"kind": "message" if text.get("message") else "appeared",
                                "element": text_element(text, selector)})
        places = {t["selector"] for t in after.get("texts", [])} | {t.get("pos") for t in after.get("texts", [])}
        gone = [t for t in old_texts if not now[t["text"]] and t.get("region") == "main" and t["selector"] not in places
                and not VOLATILE.search(t["text"]) and not secret(t["text"])]
        changes += [{"kind": "disappeared", "element": text_element(t, t["selector"])} for t in gone[:2]]
        old_boxes = {e["locators"][0]["value"]: e for e in before.get("elements", []) if e.get("locators")}
        for element in after.get("elements", []):
            previous = old_boxes.get((element.get("locators") or [{}])[0].get("value"))
            if (previous and element.get("input_type") in ("checkbox", "radio")
                    and bool(previous.get("checked")) != bool(element.get("checked"))):
                changes.append({"kind": "checked", "element": element, "after": bool(element.get("checked"))})
        return changes[:12]

    @staticmethod
    def heading(after: dict, before: dict) -> dict | None:
        """The new page's or dialog's heading: what tells a user where they are."""
        old = {e.get("text") for e in before.get("elements", [])}
        for element in after.get("elements", []):
            if (element.get("class_name") in ("h1", "h2") and element.get("region") in ("main", "dialog")
                    and usable(element) and element.get("text") and element["text"] not in old):
                return element
        return None

    # -------- pages and states
    def add_page(self, screen: dict, role: str, reached: str) -> dict | None:
        """A page of the website reached for the first time: recorded with its screenshot."""
        key = page_key(screen.get("web_url"))
        if key in self.pages:
            return self.pages[key]
        if len(self.pages) >= self.max_pages:
            self.tried.append({"check": f"Record '{screen.get('screen_name')}'", "outcome": "not attempted",
                               "reason": f"not recorded: the limit of {self.max_pages} pages for one run was reached",
                               "detail": "", "screen": screen.get("screen_name")})
            return None
        page = dict(screen)
        page.pop("alerts", None)
        page.update(nav_steps=[{"action": "open", "value": page["web_url"]}], open_by_url=True, site_role=role,
                    reached_by=reached[:160])
        self.device.record(page)
        self.pages[key] = page
        self.record_protected_controls(page)
        return page

    def add_state(self, screen: dict, steps: list[dict], parent: dict, title: str) -> dict:
        """A dialog or panel on a page (same address): its forms and buttons are tested from the steps that open it."""
        key = (parent["id"], title.casefold())
        for state in self.states:
            if state.get("state_key") == key:
                return state
        state = dict(screen)
        state.pop("alerts", None)
        state.update(nav_steps=self.nav(parent) + steps, site_role="dialog", state_key=key,
                     screen_name=f"'{title}' on {parent['screen_name']}"[:120])
        self.states.append(state)
        self.record_protected_controls(state)
        return state

    def excluded(self, screen: dict, element: dict, reason: str) -> None:
        key = ("protected", label(element).casefold())
        if key in self.seen:
            return
        self.seen.add(key)
        item = {"check": f"Tap '{nm(element)}' on {screen['screen_name']}", "outcome": "intentionally excluded",
                "detail": "", "screen": screen["screen_name"], "reason": reason}
        self.tried.append(item)
        self._covered.add(id(item))
        self.cover("control", f"'{nm(element)}'", "not tested", reason, where=screen["screen_name"])

    def outside(self, element: dict) -> str:
        """'' for a link inside the approved website; else why it is not followed."""
        href = element.get("href") or ""
        scheme = urlsplit(href).scheme.casefold()
        if scheme in ("mailto", "tel", "sms"):
            return "it opens another app (e-mail, phone or SMS), which is never used"
        if scheme in ("http", "https") and origin(href) != self.origin:
            return "it opens another website (outside the approved address), which is never followed"
        return ""

    def never(self, element: dict) -> str:
        """Why test mode never presses this control ('' = it may)."""
        href = element.get("href") or ""
        reason = self.protected(label(element) + " " + urlsplit(href).path.replace("/", " "))
        if not reason and href and PROTECTED_PATH.search(urlsplit(href).path):
            reason = "checkout, payment and placing an order are never tested"
        return reason

    # -------- 1. every menu first
    def toggles(self, screen: dict) -> list[dict]:
        out, keys = [], set()
        for element in screen.get("elements", []):
            # A control that opens a dialog ("Log in", "Sign up") is a menu entry even when the page reader also
            # called it a toggle (demoblaze, run android_20261110_113902_88059d): its dialog holds a form to fill.
            if not (usable(element) and element.get("toggle") and not element.get("opens_dialog")
                    and element.get("region") in MENU_REGIONS):
                continue
            key = (element.get("region"), label(element).casefold() or element["locators"][0]["value"])
            if key in keys or self.never(element):
                continue
            keys.add(key)
            out.append(element)
        return out

    def collect_entries(self, screen: dict, via: list[dict], only: list[dict] | None = None) -> None:
        for element in only if only is not None else screen.get("elements", []):
            opens_dialog = bool(element.get("opens_dialog"))
            if (not usable(element) or element.get("input_capable") or not element.get("clickable")
                    or (element.get("toggle") and not opens_dialog) or element.get("focus_only") or element.get("group")
                    or element.get("region") not in MENU_REGIONS or not label(element)
                    or not (element.get("href") or element.get("class_name") == "a" or opens_dialog
                            or element.get("navigation_role") in ("tab", "menu_item"))):
                continue  # menus hold links and dialog openers; a form's button (Search) is tested with its form
            away = self.outside(element)
            if away:
                self.external.setdefault(nm(element), (element.get("region"), away))
                continue
            reason = self.never(element)
            if reason:
                self.excluded(screen, element, reason)
                continue
            href = element.get("href") or ""
            key = page_key(href) if urlsplit(href).scheme in ("http", "https") and "#" not in href \
                else ("label", label(element).casefold())
            if key == page_key(screen.get("web_url")) and not via:
                key = ("self", key)  # the start page's own link (the logo, "Home")
                if key not in self.entry_keys:
                    self.entry_keys.add(key)
                    self.cover("menu", f"Menu entry '{nm(element)}'", "not tested",
                               "it opens the start page itself, which every check starts from", where="start page")
                continue
            if key in self.entry_keys:
                continue
            self.entry_keys.add(key)
            self.entries.append({"element": element, "via": list(via),
                                 "region": "footer" if element.get("region") == "footer" else "menu"})

    def menu_items(self):
        home = self.screens[0]
        self.collect_entries(home, [])
        self.toggle_queue.extend([toggle] for toggle in self.toggles(home))
        while self.toggle_queue:
            chain = self.toggle_queue.popleft()
            yield {"area": "menu", "name": f"Open the menu control '{nm(chain[-1])}'", "where": "start page",
                   "run": self.toggle_check, "args": (chain,)}
        counts = {"menu": 0, "footer": 0}
        for entry in sorted(self.entries, key=lambda e: e["region"] == "footer"):
            region = entry["region"]
            what = f"{'Footer link' if region == 'footer' else 'Menu entry'} '{nm(entry['element'])}'"
            counts[region] += 1
            if not full_run(self.device.config) and counts[region] > (FOOTER_CAP if region == "footer" else MENU_CAP):
                self.cover(region, what, "not tested", f"over the limit of {FOOTER_CAP if region == 'footer' else MENU_CAP} "
                           f"{region} entries checked in one run", where="start page")
                continue
            yield {"area": region, "name": what, "where": "start page", "run": self.entry_check, "args": (entry,)}

    def toggle_check(self, chain: list[dict]):
        """A menu button (the phone menu, a category's arrow, a footer section) opens and shows its entries."""
        home = self.screens[0]
        steps = chain_steps(chain)
        what = f"Open the menu '{nm(chain[-1])}'"
        before, after = self.observe_after(home, steps)
        if after is None:
            self.tried.append({"check": what, "outcome": "opens another app", "detail": "", "screen": "start page"})
            return
        # A menu control that opens a dialog (a login pop-up behind an "Account" button): the dialog is a state, so
        # its forms are filled and submitted like a page's.
        self.dialog_state(before, after, steps, home, nm(chain[-1]))
        # What this menu control adds to what its parent menu already showed
        parent = tuple(e["locators"][0]["value"] for e in chain[:-1])
        shown = self.opened.get(parent) or {e["locators"][0]["value"] for e in before.get("elements", []) if usable(e)}
        visible = {e["locators"][0]["value"] for e in after.get("elements", []) if usable(e)}
        self.opened[parent + (chain[-1]["locators"][0]["value"],)] = visible
        fresh = [e for e in after.get("elements", []) if usable(e) and e["locators"][0]["value"] not in shown
                 and e.get("clickable") and not e.get("input_capable")]
        links = [e for e in fresh if (not e.get("toggle") or e.get("opens_dialog")) and label(e)]
        nested = [e for e in fresh if e.get("toggle") and not e.get("opens_dialog") and not self.never(e)
                  and e["locators"][0]["value"] not in parent + (chain[-1]["locators"][0]["value"],)]
        if not links and not nested:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": "start page"})
            return
        self.collect_entries(after, chain, only=links)
        if len(chain) < 3:
            self.toggle_queue.extend(chain + [toggle] for toggle in (nested if full_run(self.device.config) else nested[:12]))
        first = (links or nested)[0]
        flow = self.build("menu", f"{what}: '{nm(first)}' appears",
                          steps + [{"action": "assert_visible", "locator": first["locators"][0]}])
        self.keep(flow, {"category": "menu", "screen_id": home["id"], "screen": home["screen_name"],
                         "element_ids": [e.get("id", "") for e in chain], "source": "interaction",
                         "expected": f"Tapping '{nm(chain[-1])}' shows its {len(links) or len(nested)} entries.",
                         "requirement": "Every menu opens (website test mode)"})

    def entry_check(self, entry: dict):
        """A menu or footer entry opens its page (or dialog); the page is recorded."""
        home, element = self.screens[0], entry["element"]
        steps = chain_steps(entry["via"]) + reach(element) + [tap(element)]
        what = f"{'Footer link' if entry['region'] == 'footer' else 'Menu entry'} '{nm(element)}'"
        before, after = self.observe_after(home, steps)
        if after is None:
            self.tried.append({"check": what, "outcome": "opens another app", "detail": "", "screen": "start page"})
            return
        self.landing(what, entry["region"], home, steps, before, after, [element])

    def landing(self, what: str, area: str, parent: dict, steps: list[dict], before: dict, after: dict,
                elements: list[dict], record: bool = True):
        """What one action did - a new page (recorded), a dialog, a change on the page - kept as a test after its
        replay. A broken page (an error / not-found page) is a finding with a failing test."""
        url = after.get("web_url") or ""
        moved = page_key(url) != page_key(before.get("web_url"))
        meta = {"category": area, "screen_id": parent["id"], "screen": parent["screen_name"],
                "element_ids": [e.get("id", "") for e in elements], "source": "interaction",
                "requirement": "Observed website behaviour in test mode (regression)"}
        if moved and (PROTECTED_PATH.search(urlsplit(url).path) or self.protected(after.get("title") or "")):
            self.tried.append({"check": what, "outcome": "intentionally excluded", "detail": "",
                               "reason": "it opens a checkout or payment page, which is never tested",
                               "screen": parent["screen_name"]})
            return
        changes = self.diff(before, after)
        if moved:
            error = self.error_mark(after)
            if error is not None:
                self.broken(what, area, parent, steps, error, meta)
                return
            if record:
                self.add_page(after, area, what)
        else:
            self.dialog_state(before, after, steps, parent, nm(elements[-1]))
        checks = assertion_steps(changes, limit=2)
        if not checks:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": parent["screen_name"]})
            return
        flow = self.build(area, f"{what}: {describe(changes)}", self.nav(parent) + steps + checks)
        self.keep(flow, {**meta, "expected": f"{what}: {describe(changes)} (as observed)."})

    def dialog_state(self, before: dict, after: dict, steps: list[dict], parent: dict, fallback: str) -> dict | None:
        """The dialog the steps opened on the same page (none was open before): kept as a state, named after the
        dialog's own title, so its forms (log in, sign up, contact) are filled and submitted like a page's.
        None when no new dialog is shown."""
        if not any(e.get("region") == "dialog" and usable(e) for e in after.get("elements", [])):
            return None
        if any(e.get("region") == "dialog" and usable(e) for e in before.get("elements", [])):
            return None
        title = next((t["text"] for t in after.get("texts", []) if t.get("region") == "dialog"), fallback)
        return self.add_state(after, steps, parent, " ".join(title.split())[:60])

    @staticmethod
    def error_mark(screen: dict) -> dict | None:
        """The heading (or title) of an error / not-found page; None for a normal page."""
        for element in screen.get("elements", []):
            if element.get("class_name") in ("h1", "h2") and usable(element) and ERROR_PAGE.search(element.get("text") or ""):
                return element
        if ERROR_PAGE.search(screen.get("title") or ""):
            return {"text": screen.get("title"), "locators": []}
        return None

    def broken(self, what: str, area: str, parent: dict, steps: list[dict], error: dict, meta: dict) -> None:
        finding = f"{what} opens an error page ('{' '.join(str(error.get('text')).split())[:80]}')"
        self.findings.append({"screen": parent["screen_name"], "finding": finding, "detail": "The page should open."})
        if not error.get("locators"):
            self.tried.append({"check": what, "outcome": "finding", "reason": finding, "detail": "",
                               "screen": parent["screen_name"]})
            return
        flow = self.build(area, f"{what} opens its page without an error",
                          self.nav(parent) + steps + [{"action": "assert_not_visible", "locator": error["locators"][0]}])
        self.keep(flow, {**meta, "expected": "The page opens; no error page is shown."}, universal=True)

    # -------- 2. every page to its end
    def read_page(self, page: dict):
        """Scroll the page to its end like a user; record the controls below the first screen and how to reach them."""
        from .android_web import how_to_reach

        self.checkpoint()
        self.read.add(page["id"])
        self.device.open(page["web_url"])
        steps = self.device.scroll_end()
        full = self.device.observe()
        viewport = full.get("viewport") or page.get("viewport") or {}
        known = {e["locators"][0]["value"]: e for e in page.get("elements", []) if e.get("locators")}
        below = 0
        for element in full.get("elements", []):
            if not element.get("locators"):
                continue
            where = how_to_reach(element, viewport)
            target = known.get(element["locators"][0]["value"])
            if target is None:
                target = {**element, "id": f"{page['id']}:e{len(page['elements']):04d}", "found_by_scrolling": True}
                page["elements"].append(target)
                known[element["locators"][0]["value"]] = target
            target.update(page_y=element.get("page_y"), how_to_reach=where,
                          web_below_fold=where != "on the first screen")
            below += target["web_below_fold"]
        page["texts"], page["viewport"] = full.get("texts", page.get("texts", [])), viewport
        self.tried.append({"check": f"Read '{page['screen_name']}' to its end", "outcome": "read", "status": "passed",
                           "reason": f"opened and scrolled to its end ({steps} scroll steps): {len(page['elements'])} "
                                     f"controls and texts, {below} of them below the first screen",
                           "detail": "", "screen": page["screen_name"], "screenshot": page.get("screenshot")})

    # -------- 3. every feature
    def web_forms(self, target: dict) -> list[dict]:
        """The forms on a page: the boxes before each submit button of one form (or one block outside a form)."""
        forms, groups = [], {}
        for element in target.get("elements", []):
            if usable(element) and element.get("group"):
                groups.setdefault(element["group"], []).append(element)
        for members in groups.values():
            pending = []
            for element in members:
                if element.get("input_capable"):
                    pending.append(element)
                    continue
                words = label(element)
                if not element.get("clickable") or element.get("href") and not element.get("submission"):
                    continue
                if not (SUBMIT.search(words) or element.get("submission")) or NOT_SUBMIT.search(words):
                    continue
                if self.never(element):
                    self.excluded(target, element, self.never(element))
                    pending = []
                    continue
                form = self.make_form(target, pending, element)
                pending = []
                if form:
                    forms.append(form)
        return forms

    def make_form(self, target: dict, boxes: list[dict], submit: dict) -> dict | None:
        texts = [b for b in boxes if b.get("class_name") != "select" and (b.get("input_type") or "") in TEXT_TYPES]
        if not texts:
            return None
        form = build_form(texts, [submit])
        form["ticks"] = [b for b in boxes if b.get("input_type") == "checkbox" and b.get("required") and not b.get("checked")]
        form["choices"] = [step for b in boxes if b.get("class_name") == "select" for step in self.choice(b)]
        words = " ".join([label(submit), *(label(b) for b in boxes), target.get("screen_name", "")])
        purpose = form["kind"]
        if purpose == "form":
            purpose = next((key for key, pattern in PURPOSES if pattern.search(words)), "form")
        elif any(CODE_BOX.search(label(b)) for b in texts):
            purpose = "code"
        form["purpose"] = purpose
        form["captcha"] = submit.get("group") in (target.get("captcha_groups") or [])
        self.form_boxes.update((target["id"], b.get("id")) for b in [*boxes, submit])
        return form

    def choice(self, select: dict) -> list[dict]:
        """A drop-down still on its empty first choice ("--- Please select ---"): choose the first real option."""
        options = select.get("options") or []
        current = next((o for o in options if o.get("selected")), options[0] if options else None)
        if current is None or (current.get("value") not in ("", "0")
                               and not re.match(r"\s*(-|select|choose|please)", current.get("text") or "", re.I)):
            return []
        option = next((o for o in options if o is not current and not o.get("disabled")
                       and o.get("value") not in ("", "0", None) and not self.protected(o.get("text") or "")), None)
        return [{"action": "select", "locator": select["locators"][0], "value": option["value"]}] if option else []

    def form_checks(self, screen: dict, form: dict):
        key = ("form", screen["id"], form["submit"]["id"])
        if key in self.seen:
            return
        purpose = form.get("purpose", form["kind"])
        if form.get("captcha") or purpose in ("login", "signup"):
            return super().form_checks(screen, form)
        self.seen.add(key)
        if purpose == "search":
            self._search_check(screen, form)
            self._search_empty_check(screen, form)
        elif purpose == "code":
            self._code_check(screen, form)
        else:
            self._form_negative_checks(screen, form)
            self._positive_form_check(screen, form, ACTION_NAMES.get(purpose, "Form submission"))

    def search_word(self) -> str:
        """A word from a product the website itself shows, so the search has results to show."""
        for page in self.pages.values():
            for element in self.card_links(page):
                word = next((w for w in re.findall(r"[A-Za-z]{4,}", element.get("text") or "")), "")
                if word:
                    return word
        return "test"

    def _search_empty_check(self, screen: dict, form: dict):
        box = next((e for e in form["inputs"] if SEARCH.search(label(e))), form["inputs"][0])
        steps = [fill(box, "")] + reach(form["submit"]) + [tap(form["submit"])]
        what = f"Search with an empty box on {screen['screen_name']}"
        before, after = self.observe_after(screen, steps)
        if after is None:
            return
        changes = self.diff(before, after)
        checks = assertion_steps(changes, limit=2)
        if not checks:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": screen["screen_name"]})
            return
        self.keep(self.build("form", f"{what}: {describe(changes)}", self.nav(screen) + steps + checks),
                  {"category": "form", "screen_id": screen["id"], "screen": screen["screen_name"],
                   "element_ids": [box.get("id", ""), form["submit"].get("id", "")], "source": "interaction",
                   "expected": f"An empty search shows: {describe(changes)} (as observed).",
                   "requirement": "Observed website behaviour in test mode (regression)"})

    def _code_check(self, screen: dict, form: dict):
        box = next(b for b in form["inputs"] if CODE_BOX.search(label(b))) if any(
            CODE_BOX.search(label(b)) for b in form["inputs"]) else form["inputs"][0]
        word = (CODE_BOX.search(label(box)) or CODE_BOX.search("coupon")).group(0).casefold()
        steps = [fill(box, "QA-INVALID-0000")] + reach(form["submit"]) + [tap(form["submit"])]
        self._refused(screen, steps, box, f"An invalid {word} code is refused on {screen['screen_name']}",
                      {"category": "form", "screen_id": screen["id"], "screen": screen["screen_name"],
                       "element_ids": [box.get("id", ""), form["submit"].get("id", "")], "source": "interaction",
                       "expected": "A made-up code is refused and the box stays.",
                       "requirement": "Standard behaviour (an invalid code is refused)"},
                      f"An invalid {word} code was accepted")

    # login: what it opens, and log out
    def after_login(self, screen: dict, flow: dict):
        if self.logged_in is None:
            self.logged_in = {"screen": screen, "steps": [s for s in flow["steps"] if not s["action"].startswith("assert_")]}
            self.queue.append({"area": "login", "name": "Explore what the login opens", "where": screen["screen_name"],
                               "run": self.behind_login, "args": ()})

    def behind_login(self):
        home, actions = self.screens[0], self.logged_in["steps"]
        before, after = self.observe_after(home, actions)
        if after is None:
            return
        known = {label(e).casefold() for e in before.get("elements", []) if usable(e)}
        known |= {label(e).casefold() for e in self.logged_in["screen"].get("elements", []) if usable(e)}
        # A greeting that names the account ("Welcome qa1a2b3c") is never opened by name: a test title, a coverage
        # row or a step would carry the account name out of the private folder.
        private = [value.casefold() for value in self.secrets.values() if value]
        fresh = [e for e in after.get("elements", []) if usable(e) and e.get("clickable") and not e.get("input_capable")
                 and label(e) and label(e).casefold() not in known
                 and not any(value in label(e).casefold() for value in private)]
        found = 0
        for element in fresh if full_run(self.device.config) else fresh[:12]:
            reason = self.outside(element) or self.never(element)
            if reason:
                self.excluded(after, element, reason)
                continue
            found += 1
            if LOGOUT.search(label(element)):
                self.queue.append({"area": "login", "name": f"Log out with '{nm(element)}'", "where": "after the login",
                                   "run": self.logout_check, "args": (element,)})
            else:
                self.queue.append({"area": "login", "name": f"After logging in, open '{nm(element)}'",
                                   "where": "after the login", "run": self.account_check, "args": (element, [], True)})
        self.tried.append({"check": "Explore what the login opens", "outcome": "read", "status": "passed",
                           "reason": f"logged in from a fresh start: {found} new controls appeared", "detail": "",
                           "screen": home["screen_name"]})

    def account_check(self, element: dict, via: list[dict], deeper: bool):
        """A page only a logged-in user sees: it opens (each check logs in again from a fresh start). Its forms are
        not submitted: they would change the test account."""
        home = self.screens[0]
        setup = self.logged_in["steps"] + chain_steps(via)
        steps = setup + reach(element) + [tap(element)]
        what = "After logging in, " + " > ".join(f"'{nm(e)}'" for e in [*via, element])
        before, after = self.observe_after(home, steps, setup=len(setup))
        if after is None:
            self.tried.append({"check": what, "outcome": "opens another app", "detail": "", "screen": "after the login"})
            return
        self.landing(what, "login", home, steps, before, after, [element], record=False)
        if deeper and page_key(after.get("web_url")) != page_key(before.get("web_url")):
            labels = {label(e).casefold() for e in before.get("elements", []) if usable(e)}
            side = [e for e in after.get("elements", []) if usable(e) and e.get("href") and e.get("region") in ("main", "aside")
                    and label(e) and label(e).casefold() not in labels and not self.outside(e)]
            for link in side if full_run(self.device.config) else side[:8]:
                reason = self.never(link)
                if reason:
                    self.excluded(after, link, reason)
                elif ("account", label(link).casefold()) not in self.done:
                    self.done.add(("account", label(link).casefold()))
                    self.queue.append({"area": "login", "name": f"After logging in, open '{nm(element)}' > '{nm(link)}'",
                                       "where": "after the login", "run": self.account_check,
                                       "args": (link, via + [element], False)})

    def logout_check(self, element: dict):
        home = self.screens[0]
        steps = self.logged_in["steps"] + reach(element) + [tap(element)]
        before, after = self.observe_after(home, steps, setup=len(self.logged_in["steps"]))
        if after is None:
            return
        self.landing(f"Log out with '{nm(element)}'", "login", home, steps, before, after, [element], record=False)

    # the cart
    def card_links(self, screen: dict) -> list[dict]:
        """Links repeated in a list of cards (products): one of them stands for all."""
        links = [e for e in screen.get("elements", []) if usable(e) and e.get("href") and e.get("region") == "main"
                 and label(e) and not self.outside(e) and not self.never(e)]
        counts = Counter(pattern(e) for e in links)
        return [e for e in links if pattern(e) and counts[pattern(e)] >= 3]

    @staticmethod
    def main_add(screen: dict) -> dict | None:
        """The page's own Add to cart button (not one of a list's repeated card buttons)."""
        adds = [e for e in screen.get("elements", []) if usable(e) and e.get("clickable") and ADD_TO_CART.search(label(e))]
        counts = Counter(pattern(e) for e in adds)
        return next((e for e in adds if counts[pattern(e)] < 3), None)

    def cart_link(self) -> dict | None:
        for element in self.screens[0].get("elements", []):
            if (usable(element) and element.get("region") in ("nav", "header") and element.get("clickable")
                    and CART_LINK.search(label(element)) and not self.never(element) and not self.outside(element)):
                return element
        return None

    def find_product(self) -> dict | None:
        """A product page: one already known, else a product card opened from a list (at most a few tries)."""
        for page in list(self.pages.values()):
            if self.main_add(page) and page is not self.screens[0]:
                return page
        tried = 0
        for page in list(self.pages.values()):
            for link in self.card_links(page):
                if tried >= PRODUCT_TRIES:
                    return None
                if page_key(link["href"]) in self.pages:
                    continue
                tried += 1
                self.checkpoint()
                live = self.device.open(link["href"])
                if self.main_add(live):
                    return self.add_page(live, "product", f"Product '{nm(link)}' opened from {page['screen_name']}")
        return None

    def options_for(self, screen: dict, add: dict) -> list[dict]:
        """Choose the options a product needs before it can be added (a drop-down on '---', no size ticked)."""
        steps, radios = [], {}
        for element in screen.get("elements", []):
            if not usable(element) or element.get("group") != add.get("group") or not element.get("group"):
                continue
            if element.get("class_name") == "select":
                steps += self.choice(element)
            elif element.get("input_type") == "radio" and element.get("name"):
                radios.setdefault(element["name"], []).append(element)
        for group in radios.values():
            if not any(e.get("checked") for e in group):
                steps.append(tap(group[0]))
        return steps

    def cart_add(self):
        product = self.find_product()
        if product is None:
            self.tried.append({"check": "Add a product to the cart", "outcome": "not attempted", "detail": "",
                               "reason": "no product page with an Add to cart button was found"})
            return
        add = self.main_add(product)
        title = next((e["text"] for e in product["elements"] if e.get("class_name") == "h1" and e.get("text")),
                     product.get("title") or product["screen_name"])
        choices = self.options_for(product, add)
        steps = choices + reach(add) + [tap(add)]
        before, after = self.observe_after(product, steps)
        what = f"Add '{' '.join(title.split())[:60]}' to the cart"
        if after is None:
            return
        changes = self.diff(before, after)
        checks = assertion_steps(changes)
        if not checks:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": product["screen_name"]})
            return

        def counted(change):
            return (change["kind"] == "text" and re.search(r"\d", change.get("before") or "")
                    and re.findall(r"\d+", change["before"]) != re.findall(r"\d+", change["after"]))
        worked = any(counted(c) or SUCCESS.search(c.get("text") or (c.get("element") or {}).get("text") or "")
                     for c in changes)
        flow = self.build("cart", f"{what}: {describe(changes)}", self.nav(product) + steps + checks)
        kept = self.keep(flow, {"category": "cart", "screen_id": product["id"], "screen": product["screen_name"],
                                "element_ids": [add.get("id", "")], "source": "interaction",
                                "expected": f"{what}: {describe(changes)} (as observed).",
                                "requirement": "Observed shop behaviour in test mode (regression)"})
        self.done.add(("words", add.get("class_name"), label(add).casefold()))  # the recipe used this button
        self.cart.update(product=product, add=add, name=" ".join(title.split()), choices=choices,
                         alerts=[s for s in checks if s["action"] == "assert_alert"], ok=bool(kept and worked))
        if kept and not worked:
            self.cart["why"] = "adding the product did not show a cart count or a success message"

    def cart_quantity(self):
        product, add = self.cart.get("product"), self.cart.get("add")
        box = next((e for e in (product or {}).get("elements", []) if usable(e) and e.get("input_capable")
                    and e.get("group") == add.get("group") and field_kind(e) == "quantity"), None) if add else None
        if box is None:
            self.tried.append({"check": "Add a quantity of 2 to the cart", "outcome": "not attempted", "detail": "",
                               "reason": "the product page has no quantity box next to Add to cart"})
            return
        steps = self.cart["choices"] + [fill(box, "2")] + reach(add) + [tap(add)]
        before, after = self.observe_after(product, steps)
        if after is None:
            return
        changes = self.diff(before, after)
        checks = assertion_steps(changes)
        what = f"Add 2 of '{self.cart['name'][:60]}' to the cart"
        if not checks:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": product["screen_name"]})
            return
        self.keep(self.build("cart", f"{what}: {describe(changes)}", self.nav(product) + steps + checks),
                  {"category": "cart", "screen_id": product["id"], "screen": product["screen_name"],
                   "element_ids": [box.get("id", ""), add.get("id", "")], "source": "interaction",
                   "expected": f"{what}: {describe(changes)} (as observed).",
                   "requirement": "Observed shop behaviour in test mode (regression)"})

    def cart_contents(self):
        what = "The cart lists the product after Add to cart"
        if not self.cart.get("ok"):
            self.tried.append({"check": what, "outcome": "not attempted", "detail": "",
                               "reason": self.cart.get("why") or "no product could be added to the cart"})
            return
        product, link = self.cart["product"], self.cart_link()
        steps = self.cart["choices"] + reach(self.cart["add"]) + [tap(self.cart["add"])] + self.cart["alerts"]
        if link is None:
            self.tried.append({"check": what, "outcome": "not attempted", "detail": "",
                               "reason": "no link to the cart was found in the page header or menu"})
            return
        setup = len(steps)
        steps += reach(link) + [tap(link)]
        before, after = self.observe_after(product, steps, setup=setup)
        if after is None:
            return
        wanted = self.cart["name"].casefold()
        line = next((t for t in after.get("texts", []) if t.get("region") == "main" and wanted in t["text"].casefold()),
                    None)
        what = f"The cart lists '{self.cart['name'][:60]}' after Add to cart"
        self.record_protected_controls({**after, "screen_name": "the cart"})  # Checkout: listed, never pressed
        if line is None:
            finding = f"The cart did not list '{self.cart['name'][:60]}' after it was added"
            self.findings.append({"screen": "the cart", "finding": finding, "detail": "Add to cart showed a result."})
            self.tried.append({"check": what, "outcome": "finding", "reason": finding, "detail": "", "screen": "the cart"})
            return
        element = text_element(line, line["selector"])
        flow = self.build("cart", what, self.nav(product) + steps
                          + [{"action": "assert_text", "locator": element["locators"][0], "value": line["text"]}])
        if self.keep(flow, {"category": "cart", "screen_id": product["id"], "screen": "the cart", "element_ids": [],
                            "source": "interaction", "expected": "The added product is listed in the cart.",
                            "requirement": "Standard shop behaviour (the cart lists what was added)"}, universal=True):
            self.cart.update(in_cart=steps, cart_screen=after, line=element)

    def cart_update(self):
        what = "Change the quantity in the cart"
        screen = self.cart.get("cart_screen")
        box = update = None
        if screen:
            box = next((e for e in screen.get("elements", []) if usable(e) and e.get("input_capable")
                        and e.get("region") == "main" and field_kind(e) == "quantity"), None)
            update = next((e for e in screen.get("elements", []) if usable(e) and e.get("clickable")
                           and UPDATE.search(label(e)) and not self.never(e)), None)
        if box is None or update is None:
            self.tried.append({"check": what, "outcome": "not attempted", "detail": "",
                               "reason": "the cart was not reached" if not screen
                               else "the cart has no quantity box with an update button"})
            return
        steps = self.cart["in_cart"] + [fill(box, "2")] + reach(update) + [tap(update)]
        self._cart_step(f"Change the quantity of '{self.cart['name'][:60]}' in the cart to 2", steps, [box, update])

    def cart_remove(self):
        what = "Remove the product from the cart"
        screen = self.cart.get("cart_screen")
        remove = next((e for e in screen.get("elements", []) if usable(e) and e.get("clickable")
                       and e.get("region") == "main" and REMOVE.search(label(e)) and not self.never(e)), None) \
            if screen else None
        if remove is None:
            self.tried.append({"check": what, "outcome": "not attempted", "detail": "",
                               "reason": "the cart was not reached" if not screen else "no remove control was found in the cart"})
            return
        steps = self.cart["in_cart"] + reach(remove) + [tap(remove)]
        self._cart_step(f"Remove '{self.cart['name'][:60]}' from the cart", steps, [remove])

    def _cart_step(self, what: str, steps: list[dict], elements: list[dict]):
        product = self.cart["product"]
        before, after = self.observe_after(product, steps, setup=len(self.cart["in_cart"]))
        if after is None:
            return
        changes = self.diff(before, after)
        checks = assertion_steps(changes)
        if not checks:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": "the cart"})
            return
        self.keep(self.build("cart", f"{what}: {describe(changes)}", self.nav(product) + steps + checks),
                  {"category": "cart", "screen_id": product["id"], "screen": "the cart",
                   "element_ids": [e.get("id", "") for e in elements], "source": "interaction",
                   "expected": f"{what}: {describe(changes)} (as observed).",
                   "requirement": "Observed shop behaviour in test mode (regression)"})

    # drop-downs and the other controls
    def select_check(self, target: dict, select: dict):
        options = select.get("options") or []
        choice = next((o for o in options if not o.get("selected") and not o.get("disabled")
                       and o.get("value") not in ("", None) and not self.protected(o.get("text") or "")), None)
        what = f"Choose an option in '{nm(select)}' on {target['screen_name']}"
        if choice is None:
            self.tried.append({"check": what, "outcome": "not attempted", "detail": "",
                               "reason": "the drop-down has no other usable choice", "screen": target["screen_name"]})
            return
        steps = reach(select) + [{"action": "select", "locator": select["locators"][0], "value": choice["value"]}]
        before, after = self.observe_after(target, steps)
        if after is None:
            return
        changes = self.diff(before, after)
        text = " ".join((choice.get("text") or "").split())
        kept_choice = {"action": "assert_text", "value": text,
                       "locator": {"strategy": "css", "value": select["locators"][0]["value"] + " option:checked"}}
        what = f"Choose '{text[:40]}' in '{nm(select)}' on {target['screen_name']}"
        self.keep(self.build("select", f"{what}: {describe(changes) if changes else 'the choice is kept'}",
                             self.nav(target) + steps + [kept_choice] + assertion_steps(changes, limit=2)),
                  {"category": "select", "screen_id": target["id"], "screen": target["screen_name"],
                   "element_ids": [select.get("id", "")], "source": "interaction",
                   "expected": f"{what}: the choice is kept" + (f", {describe(changes)}" if changes else "") + ".",
                   "requirement": "Observed website behaviour in test mode (regression)"})

    def control_check(self, target: dict, element: dict):
        steps = reach(element) + [tap(element)]
        what = f"Tap '{nm(element)}' on {target['screen_name']}"
        before, after = self.observe_after(target, steps)
        if after is None:
            self.tried.append({"check": what, "outcome": "opens another app", "detail": "", "screen": target["screen_name"]})
            return
        self.landing(what, "control", target, steps, before, after, [element])

    def selects(self, target: dict) -> list[dict]:
        out = []
        for element in target.get("elements", []):
            if (not usable(element) or element.get("class_name") != "select"
                    or (target["id"], element.get("id")) in self.form_boxes):
                continue
            key = ("select", target["id"], element.get("name") or element["locators"][0]["value"])
            if key in self.done:
                continue
            self.done.add(key)
            reason = self.never(element)
            if reason:
                self.excluded(target, element, reason)
            else:
                out.append(element)
        return out

    def controls(self, target: dict) -> list[dict]:
        """Every distinct eligible control, scoped to its page or dialog."""
        elements = [e for e in target.get("elements", []) if usable(e)]
        out = []
        for element in elements:
            tickable = element.get("input_capable") and element.get("input_type") in ("checkbox", "radio")
            if not (element.get("clickable") and not element.get("input_capable") or tickable):
                continue
            if (target["id"], element.get("id")) in self.form_boxes or element.get("focus_only"):
                continue
            if element.get("region") in MENU_REGIONS and (element.get("toggle") or element.get("href")):
                continue  # the menus were checked first
            if not label(element):
                continue
            away = self.outside(element)
            if away:
                self.external.setdefault(nm(element), (element.get("region"), away))
                continue
            reason = self.never(element)
            if reason:
                self.excluded(target, element, reason)
                continue
            key = ("control", target["id"], family(element))
            if key in self.done:
                continue
            self.done.add(key)
            out.append(element)
        out.sort(key=lambda e: (not (e.get("href") and e.get("region") == "main"), e.get("region") != "main"))
        return out

    def has_shop(self) -> bool:
        return self.cart_link() is not None or any(self.main_add(p) or any(
            ADD_TO_CART.search(label(e)) for e in p.get("elements", [])) for p in self.pages.values())

    def feature_items(self):
        processed = set()
        while True:
            batch = [t for t in [*self.pages.values(), *self.states] if t["id"] not in processed]
            if not batch and not self.queue:
                return
            processed.update(t["id"] for t in batch)
            for target in batch:
                if target.get("open_by_url") and target["id"] not in self.read:
                    yield {"area": "page", "name": f"Read '{target['screen_name']}' to its end",
                           "where": target["screen_name"], "run": self.read_page, "args": (target,)}
            forms = [(t, f) for t in batch for f in self.web_forms(t)]
            forms.sort(key=lambda item: ORDER.get(item[1]["purpose"], 9))
            for target, form in forms:
                key = ("form", target["id"], form["submit"]["id"],
                       tuple(sorted(label(b).casefold() for b in form["inputs"])))
                if key in self.done:
                    continue
                self.done.add(key)
                title = ACTION_NAMES.get(form["purpose"], form["purpose"].title()).replace("Form submission", "Form")
                yield {"area": "form", "name": f"{title} on {target['screen_name']}".replace("Signup", "Sign-up form"),
                       "where": target["screen_name"], "run": self.form_checks, "args": (target, form)}
            if not self.cart.get("planned") and self.has_shop():
                self.cart["planned"] = True
                for what, run in (("Add a product to the cart", self.cart_add),
                                  ("Add a quantity of 2 to the cart", self.cart_quantity),
                                  ("The cart lists the added product", self.cart_contents),
                                  ("Change the quantity in the cart", self.cart_update),
                                  ("Remove the product from the cart", self.cart_remove)):
                    yield {"area": "cart", "name": what, "where": "the cart", "run": run, "args": ()}
            for target in batch:
                for select in self.selects(target):
                    yield {"area": "select", "name": f"Drop-down '{nm(select)}' on {target['screen_name']}",
                           "where": target["screen_name"], "run": self.select_check, "args": (target, select)}
            for target in batch:
                for element in self.controls(target):
                    yield {"area": "control", "name": f"Tap '{nm(element)}' on {target['screen_name']}",
                           "where": target["screen_name"], "run": self.control_check, "args": (target, element)}
            while self.queue:
                yield self.queue.popleft()

    # -------- everything, in order
    def plan(self):
        yield from self.menu_items()
        yield from self.feature_items()

    def finish(self):
        for label_text, (region, reason) in sorted(self.external.items()):
            self.cover("footer" if region == "footer" else "control", f"'{label_text}'", "not tested", reason)
        self.cover("phone", "Rotate, leave and come back, Back button", "not tested",
                   "these phone checks are for apps; a website in Chrome is checked page by page")

    def run(self, ask=None, requirements: str = "") -> str:
        """Menus, then pages, then features, then (with AI) journeys. Returns why it stopped ('' = done)."""
        self.reserve = 6 if ask else 0
        for screen in list(self.screens):
            self.record_protected_controls(screen)
        stopped = self.execute(self.plan())
        self.finish()
        return self.journeys(ask, requirements, stopped)
