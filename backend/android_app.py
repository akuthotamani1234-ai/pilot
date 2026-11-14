"""Test mode for a native app TEST BUILD: use every screen, menu, button and form like a real user, except checkout.

Built on the same core as websites (android_interact.Session: a fresh app per check, a replay before a test is kept,
the coverage list). The order a manual tester follows:
  1. the app menu first: open the drawer, open every item and check its screen's heading (a screen that offers a
     device feature - camera, location, fingerprint, USB - may be opened; the feature itself is never used, and an
     Android permission prompt is declined)
  2. every screen reached that way, the first item of each list (a product), its controls (+ / -, Add To Cart twice,
     rating stars - one of a kind), the Sort sheet with every option (the order must change), the cart (it must list
     the product; + / -; Remove Item -> the empty cart; Go Shopping)
  3. forms: login with empty fields, a wrong password, the locked-out sample user, the sample user or your test
     account, then Log Out from the menu; sign-up with generated test data
  4. phone checks (rotate, leave and come back, Back) and, with AI, journeys
Never pressed: checkout, payment, placing an order, deleting an account, crash buttons, resetting the app, sharing,
calls and SMS (qa_contracts.never_in_test_mode). Every check ends in the coverage list with a plain reason.
"""

import re
from collections import Counter, deque

from .android import repeat_family
from .android_coverage import full_run
from .android_design import normalize_screens
from .android_interact import (
    Session,
    anchor,
    anchor_checks,
    assertion_steps,
    describe,
    family,
    find_form,
    label,
    name,
    reach,
    reversible_candidates,
    tap,
    usable,
)

MENU_BUTTON = re.compile(r"\b(menu|navigation|drawer|hamburger)\b", re.I)
SORT = re.compile(r"\bsort", re.I)
ADD_TO_CART = re.compile(r"\badd to (?:cart|basket|bag)\b", re.I)
CART = re.compile(r"\b(view )?(cart|basket|bag)\b", re.I)
PLUS = re.compile(r"\b(increase|plus|add one|more)\b|^\+$", re.I)
MINUS = re.compile(r"\b(decrease|minus|remove one|less)\b|^[-−]$", re.I)
LOGOUT = re.compile(r"\b(log ?out|sign ?out)\b", re.I)
LOCKED = re.compile(r"locked\s*out", re.I)


def nm(element: dict) -> str:
    return " ".join(name(element).split())[:60]


class AppSession(Session):
    """User-like testing of a native app test build (see the module docstring)."""

    def __init__(self, device, environment=None):
        super().__init__(device, environment)
        self.states: list[dict] = []
        self.done: set = set()
        self.queue: deque = deque()
        self.menu: dict = {}
        self.logged_in: dict | None = None
        self.product: dict = {}

    # -------- navigation: recorded screens by their discovery path, states by the taps that open them
    def nav(self, screen: dict) -> list[dict]:
        return list(screen["nav_steps"]) if "nav_steps" in screen else super().nav(screen)

    def go_to(self, screen: dict, fresh: bool = True) -> dict:
        if "nav_steps" not in screen:
            return self.device.go_to(screen)
        live = self.device.fresh_start()
        if screen["nav_steps"]:
            self.perform(screen["nav_steps"])
            live = self.device.observe()
        return live


    def add_state(self, screen: dict, steps: list[dict], title: str, role: str) -> dict:
        from .android_runtime import screen_key

        key = (role, screen_key(screen))
        for state in self.states:
            if state.get("state_key") == key:
                return state
        state = dict(screen)
        state.update(nav_steps=list(steps), state_key=key, site_role=role,
                     screen_name=" ".join(title.split())[:100] or screen.get("screen_name", "screen"))
        path = self.record_path(steps)
        record = getattr(self.device, "record", None)
        if path is not None and record is not None:
            # Reached by safe navigation (the menu button, then 'Log In'): a screen of the run like any other, with
            # its path, so its UI checks, forms and controls are tested and the final run can reopen it
            state["path"] = path
            record(state, path)
        else:
            normalize_screens([state])
            self.states.append(state)
        self.record_protected_controls(state)
        return state

    def record_path(self, steps: list[dict]) -> list[str] | None:
        """The recorded safe-navigation controls these taps are (element ids), or None when one of them is not."""
        from .android import safe_navigation_elements

        path = []
        for step in steps:
            if step.get("action") == "scroll_to":
                continue
            if step.get("action") != "tap":
                return None
            match = next((e for screen in self.screens for e in safe_navigation_elements(screen)
                          if e.get("locators", [])[:1] == [step["locator"]]), None)
            if match is None:
                return None
            path.append(match["id"])
        return path or None

    def heading(self, after: dict, before: dict) -> dict | None:
        """What identifies the screen that opened: a heading that was not on the screen before."""
        common = {family(e) for e in before.get("elements", []) if usable(e)}
        return anchor(after, common)

    def opened(self, what: str, area: str, parent: dict, steps: list[dict], before: dict, after: dict,
               element: dict, role: str = "screen", universal: bool = False) -> dict | None:
        """A tap that opens a screen: its heading is asserted, and the screen is tested in the next phase (unless it
        is a screen already tested, such as Catalog opening Products)."""
        mark = self.heading(after, before)
        changes = self.diff(before, after)
        checks = anchor_checks(mark) if mark is not None else assertion_steps(changes)
        if not checks:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "",
                               "screen": parent["screen_name"]})
            return None
        title = (mark or {}).get("text") or (mark or {}).get("accessibility_id") or after.get("screen_name", "")
        state = self.remember_destination(parent, steps, after, str(title), role)
        flow = self.build(area, f"{what}: '{' '.join(str(title).split())[:50]}' opens" if mark else
                          f"{what}: {describe(changes)}", self.nav(parent) + steps + checks)
        self.keep(flow, {"category": area, "screen_id": parent["id"], "screen": parent["screen_name"],
                         "element_ids": [element.get("id", "")], "source": "interaction",
                         "expected": f"{what} opens its screen (as observed).",
                         "requirement": "Observed app behaviour on a test build (regression)"}, universal=universal)
        return state

    def remember_destination(self, parent, steps, after, title, role):
        from .android_runtime import same_screen

        known = next((k for k in [*self.screens, *self.states] if k.get("package_name") == after.get("package_name")
                      and same_screen(after, k)), None)
        if known is not None:
            # Already recorded by discovery (it is reached by its own path) or already a state: tested once, with
            # the role this tap revealed (a product screen gets the quantity and cart checks)
            if role in ("item", "cart") and known.get("site_role") in (None, "screen", "menu"):
                known["site_role"] = role
            state = known
        else:
            # Recorded now, while it is on the device (its screenshot), before the replay below
            state = self.add_state(after, self.nav(parent) + steps, str(title), role)
        return state

    def on_observed_action(self, screen, element, steps, before, after):
        from .android_runtime import same_screen

        if not same_screen(after, screen):
            self.remember_destination(screen, steps, after, after.get("screen_name", "Screen"), "screen")

    def declined_prompts(self) -> list[str]:
        """Android permission prompts declined since the last call (test mode never allows a device feature)."""
        prompts = getattr(self.device.driver, "_blowai_declined", None)
        if not prompts:
            return []
        taken = list(prompts)
        prompts.clear()
        return taken

    # -------- 1. the app menu first
    def menu_button(self, screen: dict) -> dict | None:
        return next((e for e in screen.get("elements", []) if usable(e) and e.get("clickable")
                     and not e.get("navigation_role") and MENU_BUTTON.search(label(e))
                     and not self.protected(label(e))), None)

    def menu_items(self):
        launch = self.screens[0]
        button = self.menu_button(launch)
        if button is None:
            return
        yield {"area": "menu", "name": f"Open the app menu '{nm(button)}'", "where": launch["screen_name"],
               "run": self.open_menu, "args": (launch, button)}
        for item in self.menu.get("items", []):
            reason = self.protected(label(item), navigation=True)
            what = f"Menu item '{nm(item)}'"
            if reason:
                self.excluded(launch, item, reason, area="menu")
                continue
            yield {"area": "menu", "name": what, "where": "the app menu", "run": self.menu_item_check,
                   "args": (launch, button, item)}

    def open_menu(self, launch: dict, button: dict):
        steps = reach(button) + [tap(button)]
        before, after = self.observe_after(launch, steps)
        if after is None:
            return
        items = [e for e in after.get("elements", []) if e.get("navigation_role") == "menu_item" and e.get("visible")
                 and e.get("locators") and (e.get("text") or e.get("accessibility_id"))]
        if not items:
            self.tried.append({"check": f"Open the app menu '{nm(button)}'", "outcome": "no visible change",
                               "detail": "", "screen": launch["screen_name"]})
            return
        self.menu = {"button": button, "items": items, "screen": after}
        flow = self.build("menu", f"Open the app menu '{nm(button)}': {len(items)} items appear",
                          self.nav(launch) + steps + [{"action": "assert_visible", "locator": items[0]["locators"][0]}])
        self.keep(flow, {"category": "menu", "screen_id": launch["id"], "screen": launch["screen_name"],
                         "element_ids": [button.get("id", "")], "source": "interaction",
                         "expected": f"The menu shows its {len(items)} items.",
                         "requirement": "Every menu opens (test mode)"})

    def menu_item_check(self, launch: dict, button: dict, item: dict):
        step = tap(item)
        if self.protected(label(item)):  # a device-feature screen (QR Code Scanner): open it, never use it
            step["purpose"] = "navigation"
        steps = reach(button) + [tap(button), step]
        what = f"Menu item '{nm(item)}'"
        self.declined_prompts()  # prompts of earlier checks' replays belong to them
        before, after = self.observe_after(launch, steps, setup=len(reach(button)) + 1)
        for prompt in self.declined_prompts():
            self.tried.append({"check": f"{what}: Android permission prompt", "outcome": "declined", "detail": "",
                               "reason": f"the permission prompt ('{prompt[:80]}') was declined: a device feature is "
                                         "never used in test mode", "screen": what})
        if after is None:
            self.tried.append({"check": what, "outcome": "opens another app", "detail": "", "screen": "the app menu",
                               "reason": "it opens another app, which is not followed"})
            return
        self.opened(what, "menu", launch, steps, before, after, item, role="menu")

    # -------- 2. screens, lists, sort, the cart
    def excluded(self, screen: dict, element: dict, reason: str, area: str = "control") -> None:
        key = ("protected", family(element))  # the same key as record_protected_controls: one row per control
        if key in self.seen:
            return
        self.seen.add(key)
        item = {"check": f"Tap '{nm(element)}' on {screen['screen_name']}", "outcome": "intentionally excluded",
                "detail": "", "screen": screen["screen_name"], "reason": reason}
        self.tried.append(item)
        self._covered.add(id(item))
        self.cover(area, f"'{nm(element)}'", "not tested", reason, where=screen["screen_name"])

    def first_item(self, screen: dict) -> dict | None:
        """The first card of a list (a product picture or title): one item stands for all."""
        clickable = [e for e in screen.get("elements", []) if usable(e) and e.get("clickable") and label(e)
                     and not e.get("navigation_role") and not self.protected(label(e))]
        counts = Counter((e.get("class_name"), e.get("accessibility_id") or e.get("resource_id")) for e in clickable)
        return next((e for e in clickable if counts[(e.get("class_name"), e.get("accessibility_id")
                                                    or e.get("resource_id"))] >= 2 and not repeat_family(e)), None)

    def open_item(self, screen: dict, element: dict):
        self.done.add((element.get("class_name"), label(element).casefold()))  # one card stands for all
        steps = reach(element) + [tap(element)]
        before, after = self.observe_after(screen, steps)
        if after is None:
            return
        state = self.opened(f"Open the first '{nm(element)}' on {screen['screen_name']}", "screen", screen, steps,
                            before, after, element, role="item")
        if state is not None and not self.product:
            self.product = {"state": state, "name": state["screen_name"]}

    def sort_check(self, screen: dict, button: dict):
        """The sort sheet: every option is tried; the order of the list must change."""
        steps = reach(button) + [tap(button)]
        before, after = self.observe_after(screen, steps)
        if after is None:
            return
        shown = {(e.get("resource_id"), e.get("text")) for e in before.get("elements", [])}
        options = [e for e in after.get("elements", []) if usable(e) and e.get("clickable") and e.get("text")
                   and (e.get("resource_id"), e.get("text")) not in shown and not self.protected(label(e))]
        if not options:
            self.tried.append({"check": f"Open '{nm(button)}'", "outcome": "no visible change", "detail": "",
                               "screen": screen["screen_name"]})
            return
        self.tried.append({"check": f"Open '{nm(button)}' on {screen['screen_name']}", "outcome": "read",
                           "status": "passed", "detail": "", "screen": screen["screen_name"],
                           "reason": f"the sheet shows {len(options)} options: "
                                     + ", ".join(nm(o) for o in options[:8])})
        for option in options if full_run(self.device.config) else options[:8]:
            self.queue.append({"area": "sort", "name": f"Sort by '{nm(option)}' on {screen['screen_name']}",
                               "where": screen["screen_name"], "run": self.sort_option, "args": (screen, button, option)})

    def sort_option(self, screen: dict, button: dict, option: dict):
        steps = reach(button) + [tap(button), tap(option)]
        before, after = self.observe_after(screen, steps)
        what = f"Sort by '{nm(option)}' on {screen['screen_name']}"
        if after is None:
            return
        changes = [c for c in self.diff(before, after) if c["kind"] == "text"]
        if not changes:
            self.tried.append({"check": what, "outcome": "no visible change", "screen": screen["screen_name"],
                               "detail": "", "reason": "the order of the list did not change (it may already be "
                                                       "in this order)"})
            return
        self.keep(self.build("sort", f"{what}: {describe(changes)}", self.nav(screen) + steps
                             + assertion_steps(changes, limit=2)),
                  {"category": "sort", "screen_id": screen["id"], "screen": screen["screen_name"],
                   "element_ids": [button.get("id", ""), option.get("id", "")], "source": "interaction",
                   "expected": f"{what}: the order changes ({describe(changes)}).",
                   "requirement": "Observed app behaviour on a test build (regression)"})

    def quantity_checks(self, state: dict):
        """+ and - on a product: the count changes and never goes below one; Add To Cart twice gives 2."""
        elements = [e for e in state.get("elements", []) if usable(e) and e.get("clickable")]
        plus = next((e for e in elements if PLUS.search(label(e))), None)
        minus = next((e for e in elements if MINUS.search(label(e))), None)
        add = next((e for e in elements if ADD_TO_CART.search(label(e))), None)
        meta = {"category": "cart", "screen_id": state["id"], "screen": state["screen_name"], "source": "interaction",
                "requirement": "Observed app behaviour on a test build (regression)"}
        for what, steps, setup in (
                (f"Tap '{nm(plus)}' then '{nm(minus)}' on {state['screen_name']}" if plus and minus else "",
                 reach(plus or {}) + [tap(plus)] + reach(minus or {}) + [tap(minus)] if plus and minus else [], 1),
                (f"Tap '{nm(minus)}' at the lowest count on {state['screen_name']}" if minus else "",
                 reach(minus or {}) + [tap(minus)] if minus else [], 0),
                (f"Add '{state['screen_name'][:40]}' to the cart twice" if add else "",
                 reach(add or {}) + [tap(add)] + reach(add or {}) + [tap(add)] if add else [], 1)):
            if not what:
                continue
            key = ("quantity", what)
            if key in self.done:
                continue
            self.done.add(key)
            self.attempt(what, self._quantity, state, what, steps, setup, meta, area="cart", where=state["screen_name"])

    def _quantity(self, state, what, steps, setup, meta):
        before, after = self.observe_after(state, steps, setup=setup)
        if after is None:
            return
        changes = self.diff(before, after)
        dropped = next((c for c in changes if "lowest" in what and c["kind"] == "text"
                        and re.fullmatch(r"\d+", c.get("before") or "") and re.fullmatch(r"\d+", c.get("after") or "")
                        and int(c["after"]) < max(1, int(c["before"]))), None)
        if dropped is not None:
            # Run android_20261110_110821_90cd6d kept "'noTV' changes from '1' to '0'" as a pass. A quantity below one
            # is a finding: the test asserts the count stays, so it fails while the app allows it.
            element = dropped["element"]
            finding = f"'-' lets the quantity drop from {dropped['before']} to {dropped['after']}"
            self.findings.append({"screen": state["screen_name"], "finding": finding,
                                  "detail": "A product's quantity should never go below one; review this."})
            flow = self.build("cart", f"{what}: the count stays '{dropped['before']}'", self.nav(state) + steps
                              + [{"action": "assert_text", "locator": element["locators"][0], "value": dropped["before"]}])
            self.keep(flow, {**meta, "element_ids": [element.get("id", "")],
                             "expected": "The count never goes below one."}, universal=True)
            return
        if not changes and "lowest" in what:
            # Nothing changed: the count stayed at its lowest value. Assert the count that is shown.
            count = next((e for e in after.get("elements", []) if usable(e) and re.fullmatch(r"\d+", e.get("text") or "")
                          and e.get("resource_id")), None)
            if count is None:
                self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": state["screen_name"]})
                return
            flow = self.build("cart", f"{what}: the count stays '{count['text']}'", self.nav(state) + steps
                              + [{"action": "assert_text", "locator": count["locators"][0], "value": count["text"]}])
            self.keep(flow, {**meta, "element_ids": [count.get("id", "")], "expected": "The count never goes below one."},
                      universal=True)
            return
        checks = assertion_steps(changes)
        if not checks:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": state["screen_name"]})
            return
        self.keep(self.build("cart", f"{what}: {describe(changes)}", self.nav(state) + steps + checks),
                  {**meta, "element_ids": [], "expected": f"{what}: {describe(changes)} (as observed)."})

    def cart_check(self, state: dict):
        """The cart after Add To Cart: it lists the product; its controls are tested from that state next."""
        launch = self.screens[0]
        add = next((e for e in state.get("elements", []) if usable(e) and ADD_TO_CART.search(label(e))), None)
        cart = next((e for e in state.get("elements", []) if usable(e) and e.get("clickable") and CART.search(label(e))
                     and not ADD_TO_CART.search(label(e))), None)
        what = f"The cart lists '{state['screen_name'][:50]}' after Add To Cart"
        if add is None or cart is None:
            self.tried.append({"check": what, "outcome": "not attempted", "detail": "", "screen": state["screen_name"],
                               "reason": "no Add To Cart button or cart button was found on the product screen"})
            return
        setup = self.nav(state) + reach(add) + [tap(add)]
        steps = setup + reach(cart) + [tap(cart)]
        before, after = self.observe_after(launch, steps, setup=len(setup))
        if after is None:
            return
        wanted = state["screen_name"].casefold()
        line = next((e for e in after.get("elements", []) if usable(e) and (e.get("text") or "").casefold() == wanted),
                    None)
        cart_state = self.add_state(after, steps, f"Cart with '{state['screen_name'][:40]}'", "cart")
        if line is None:
            finding = f"The cart did not list '{state['screen_name'][:50]}' after Add To Cart"
            self.findings.append({"screen": "the cart", "finding": finding, "detail": "Add To Cart was tapped."})
            self.tried.append({"check": what, "outcome": "finding", "reason": finding, "detail": "", "screen": "the cart"})
            return
        locator = line["locators"][0]
        self.keep(self.build("cart", what, steps + [{"action": "assert_text", "locator": locator, "value": line["text"]}]),
                  {"category": "cart", "screen_id": launch["id"], "screen": "the cart", "source": "interaction",
                   "element_ids": [add.get("id", ""), cart.get("id", "")],
                   "expected": "The added product is listed in the cart.",
                   "requirement": "Standard shop behaviour (the cart lists what was added)"}, universal=True)
        return cart_state

    def controls(self, state: dict) -> list[dict]:
        """Every distinct eligible control on this state; the run budget reports any unfinished work."""
        out = []
        for element in reversible_candidates(state, native=True):
            if element.get("navigation_role") or MENU_BUTTON.search(label(element)) or SORT.search(label(element)):
                continue  # the menu and the sort sheet have their own checks
            if state.get("site_role") == "item" and MINUS.search(label(element)):
                continue  # '-' on a product has its own checks (with '+', and at the lowest count)
            key = ("control", state["id"], family(element))
            if key in self.done:
                continue
            self.done.add(key)
            out.append(element)
        return out

    # -------- 3. login and log out
    def after_login(self, screen: dict, flow: dict):
        if self.logged_in is not None:
            return
        self.logged_in = {"screen": screen, "steps": [s for s in flow["steps"] if not s["action"].startswith("assert_")]}
        if self.menu.get("button"):
            self.queue.append({"area": "login", "name": "Log out from the app menu", "where": "the app menu",
                               "run": self.logout_check, "args": ()})
        discover = getattr(self.device, "on_authenticated", None)
        if discover:
            self.attempt("Explore screens after test-account login", discover, flow, area="login")

    def logout_check(self):
        launch, button = self.screens[0], self.menu["button"]
        setup = self.logged_in["steps"]
        steps = setup + reach(button) + [tap(button)]
        before, after = self.observe_after(launch, steps, setup=len(setup))
        if after is None:
            return
        item = next((e for e in after.get("elements", []) if e.get("navigation_role") == "menu_item"
                     and LOGOUT.search(label(e))), None)
        what = "Log out from the app menu"
        if item is None:
            self.tried.append({"check": what, "outcome": "not attempted", "detail": "", "screen": "the app menu",
                               "reason": "the menu shows no Log Out item after logging in"})
            return
        steps = steps + [tap(item)]
        before, after = self.observe_after(launch, steps, setup=len(setup))
        if after is None:
            return
        # "Are you sure you want to log out?" -> its Log Out / Yes button (never a Cancel); the app's answer is checked
        confirm = next((e for e in after.get("elements", []) if usable(e) and e.get("clickable")
                        and re.fullmatch(r"\s*(log ?out|sign ?out|yes|confirm)\s*", e.get("text") or "", re.I)), None)
        if confirm is not None:
            steps = steps + [tap(confirm)]
            before, after = self.observe_after(launch, steps, setup=len(setup))
            if after is None:
                return
        changes = self.diff(before, after)
        checks = assertion_steps(changes, limit=2)
        if not checks:
            self.tried.append({"check": what, "outcome": "no visible change", "detail": "", "screen": "the app menu"})
            return
        self.keep(self.build("login", f"{what}: {describe(changes)}", steps + checks),
                  {"category": "login", "screen_id": launch["id"], "screen": "the app menu", "source": "interaction",
                   "element_ids": [item.get("id", "")], "expected": f"Logging out works: {describe(changes)}.",
                   "requirement": "Observed app behaviour on a test build (regression)"})

    # -------- everything, in order
    def targets(self):
        return [*self.screens, *[s for s in self.states if not any(s is k for k in self.screens)]]

    def feature_items(self):
        processed = set()
        launch = self.screens[0]
        while True:
            batch = [t for t in self.targets() if id(t) not in processed]
            if not batch and not self.queue:
                return
            processed.update(id(t) for t in batch)
            for target in batch:
                form = find_form(target, True)
                if form and ("form", target["id"], form["submit"]["id"]) not in self.seen:
                    yield {"area": "form", "name": f"{form['kind'].title()} form on {target['screen_name']}",
                           "where": target["screen_name"], "run": self.form_checks, "args": (target, form)}
            for target in batch:
                if target is launch or target.get("site_role") in ("menu",):
                    item = self.first_item(target)
                    if item is not None and ("item", target["screen_name"]) not in self.done:
                        self.done.add(("item", target["screen_name"]))
                        yield {"area": "screen", "name": f"Open the first '{nm(item)}' on {target['screen_name']}",
                               "where": target["screen_name"], "run": self.open_item, "args": (target, item)}
                sort = next((e for e in target.get("elements", []) if usable(e) and e.get("clickable")
                             and SORT.search(label(e)) and not self.protected(label(e))), None)
                if sort is not None and ("sort", label(sort).casefold()) not in self.done:
                    self.done.add(("sort", label(sort).casefold()))
                    yield {"area": "sort", "name": f"Open '{nm(sort)}' on {target['screen_name']}",
                           "where": target["screen_name"], "run": self.sort_check, "args": (target, sort)}
            for target in batch:
                if target.get("site_role") == "item":
                    self.quantity_checks(target)
                    if not self.product.get("cart"):
                        self.product["cart"] = True
                        yield {"area": "cart", "name": f"The cart lists '{target['screen_name'][:50]}'",
                               "where": "the cart", "run": self.cart_check, "args": (target,)}
            for target in batch:
                for element in self.controls(target):
                    yield {"area": "control", "name": f"Tap '{nm(element)}' on {target['screen_name']}",
                           "where": target["screen_name"], "run": self.tap_check, "args": (target, element)}
            while self.queue:
                yield self.queue.popleft()

    def plan(self):
        yield from self.menu_items()
        yield from self.feature_items()
        yield {"area": "phone", "name": "Rotation, background and Back checks", "where": self.screens[0]["screen_name"],
               "run": self.device_checks, "args": ()}

    def run(self, ask=None, requirements: str = "") -> str:
        """Menu, screens, forms, phone checks, then (with AI) journeys. Returns why it stopped ('' = done)."""
        self.reserve = 6 if ask else 0
        for screen in self.screens:
            self.record_protected_controls(screen)
        stopped = self.execute(self.plan())
        return self.journeys(ask, requirements, stopped)
