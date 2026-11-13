"""Test mode for a website in Android Chrome ("test everything except checkout"), run offline against a fake shop
(tests/android_fake_site.py) through the real pipeline: bot checks, every menu first, every page to its end, every
feature from a fresh visit, the cart, login with the account it registered, the coverage report.

Lessons from real runs: runs/android_20261109_224330_375ab7 and runs/android_20261109_224715_7c569b only ever saw
Cloudflare's "Performing security verification" page on demo.nopcommerce.com and made UI tests from it (Ray ID ...);
runs/android_20261109_225228_fc7aa5 (demoblaze) saw 3 screens and left 21 items unvisited.
"""

import json
import time
from pathlib import Path

import pytest

from backend import android_pipeline
from backend.android_web import BotCheckGate, bot_check, guard_url
from backend.qa_contracts import origin, parse_contract
from tests.android_fake_site import BASE, FakeShop

CONFIG = {"app_mode": "web", "device_id": "emulator-5554", "start_url": BASE + "/", "interaction_testing": True,
          "max_actions": 60, "max_screens": 40, "discovery_timeout_s": 600, "max_interactions": 500,
          "interaction_timeout_s": 3600, "bot_check_wait_s": 30, "human_wait_s": 60}


class VirtualClock:
    """Waiting advances a virtual clock: bounded waits end at once, without sleeping."""

    def __enter__(self):
        self.offset, self.real = [0.0], (time.sleep, time.monotonic)
        real_monotonic = time.monotonic
        time.sleep = lambda seconds: self.offset.__setitem__(0, self.offset[0] + seconds)
        time.monotonic = lambda: real_monotonic() + self.offset[0]
        return self

    def __exit__(self, *_):
        time.sleep, time.monotonic = self.real


def explore(tmp_path, shop, **config):
    with VirtualClock():
        original = android_pipeline.create_session
        android_pipeline.create_session = lambda _config: shop
        try:
            state = {"config": {**CONFIG, **config}, "run_dir": str(tmp_path), "log": []}
            return {**state, **android_pipeline.discovery_agent(state)}
        finally:
            android_pipeline.create_session = original


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """One full test-mode exploration of the fake shop, shared by the checks below."""
    shop = FakeShop()
    folder = tmp_path_factory.mktemp("site")
    result = explore(folder, shop)
    return {"shop": shop, "result": result, "dir": folder,
            "titles": [item["flow"]["title"] for item in result["auto_flows"]],
            "rows": result["interaction"]["coverage"]}


def flow(run, start):
    return next(item["flow"] for item in run["result"]["auto_flows"] if item["flow"]["title"].startswith(start))


# ------------------------------------------------------------------ 1. bot checks

@pytest.mark.parametrize("title, text, frames, markers", [
    ("Just a moment...", "Performing security verification. Ray ID: 9a", [], []),
    ("shop", "Checking your browser before accessing shop.example.test", [], []),
    ("Attention Required! | Cloudflare", "Please complete the security check to access", [], []),
    ("Verify you are human", "", ["www.google.com"], []),
    ("shop", "Verify you are human by completing the action below.", ["challenges.cloudflare.com"], ["#challenge-stage"]),
    ("One more step", "Please complete the security check", ["newassets.hcaptcha.com"], [".h-captcha"]),
    ("shop", "Are you a robot?", ["www.google.com/recaptcha"], [".g-recaptcha"]),
])
def test_bot_check_pages_are_recognised(title, text, frames, markers):
    data = {"title": title, "elements": [], "challenge": {"text": text, "frames": frames, "markers": markers}}
    assert bot_check(data)


def test_a_captcha_inside_a_real_page_is_not_a_bot_check_page():
    """A shop's own contact form with a reCAPTCHA box is a normal page (the form is reported as CAPTCHA-protected)."""
    elements = [{"clickable": True}] * 60
    data = {"title": "Shop. Contact Us", "elements": elements,
            "challenge": {"text": "Contact us ... I'm not a robot", "frames": ["www.google.com/recaptcha"],
                          "markers": [".g-recaptcha", "[data-sitekey]"]}}
    assert bot_check(data) == ""


def test_a_bot_check_that_clears_is_waited_for_and_never_becomes_a_screen_or_a_test(tmp_path):
    shop = FakeShop(bot="clears", bot_reads=3)
    result = explore(tmp_path, shop, interaction_testing=False)
    assert result["screens"] and all("moment" not in s["screen_name"].casefold() for s in result["screens"])
    assert result["bot_check"]["events"][0]["outcome"] == "finished by itself"
    assert not result["bot_check"]["blocked"]
    assert "Ray ID" not in json.dumps(result["screens"])


def test_a_bot_check_nobody_completes_asks_a_person_then_stops_with_a_plain_message(tmp_path, capsys):
    result = explore(tmp_path, FakeShop(bot="never"))
    out = capsys.readouterr().out
    asked = [json.loads(line[len("::human::"):]) for line in out.splitlines() if line.startswith("::human::")]
    assert asked[0]["what"] == "bot_check" and asked[0]["wait_s"] == 60
    assert asked[-1] == {"what": "bot_check", "done": True, "ok": False}
    assert result["screens"] == [] and result["auto_flows"] == []  # nothing made from the check page
    assert result["bot_check"]["blocked"] and "blocks automated visitors" in result["bot_check"]["message"]
    assert "Nothing behind it was tested" in result["setup_error"] or "blocks automated" in result["setup_error"]
    # The report says it at the top, before anything else
    from backend.android_reporting import report
    state = {**result, "run_id": "r", "test_cases": [], "results": [], "failures": []}
    report(state)
    page = (tmp_path / "report.html").read_text(encoding="utf-8")
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert page.index("Stopped at the website's bot check") < page.index("Quality gates")
    assert summary["bot_check"]["blocked"] and summary["incomplete_reason"].startswith("The website blocks")


def test_a_person_completing_the_bot_check_lets_testing_continue():
    shop = FakeShop(bot="person")
    gate = BotCheckGate({"bot_check_wait_s": 10, "human_wait_s": 120})
    gate.on_ask = lambda: setattr(shop, "bot", "")  # the person solves it on the emulator

    def read():
        return shop.execute_script(__import__("backend.android_web", fromlist=["DOM_SCRIPT"]).DOM_SCRIPT,
                                   {"test_mode": True})
    with VirtualClock():
        data = gate(shop, "Cloudflare: Performing security verification", read)
    assert data["title"] == "Shop. Home" and gate.events[0]["outcome"] == "completed by a person"


def test_blow_ai_never_changes_its_identity_to_get_past_a_bot_check():
    """No fake user agent, stealth script or solver: the Chrome capabilities stay the honest defaults."""
    from backend import android
    source = Path(android.__file__).read_text(encoding="utf-8") + Path(
        __import__("backend.android_web", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    for forbidden in ("user-agent", "userAgent", "webdriver', {get", "navigator.webdriver", "stealth", "2captcha",
                      "anti-captcha", "capsolver"):
        assert forbidden not in source


# ------------------------------------------------------------------ 2. every menu first

def test_every_menu_is_opened_first_and_each_entry_opens_its_page(run):
    titles = run["titles"]
    menus = [t for t in titles if t.startswith(("Open the menu", "Menu entry", "Footer link"))]
    assert titles[:len(menus)] == menus  # menus first in the budget
    assert "Open the menu 'Categories': 'Computers' appears" in titles  # the phone menu button
    assert "Open the menu 'Show the Computers sub-menu': 'Desktops' appears" in titles  # a category's sub-menu
    assert "Open the menu 'Information': 'About us' appears" in titles  # a footer section
    for entry in ("Menu entry 'Computers'", "Menu entry 'Desktops'", "Menu entry 'Books'", "Menu entry 'Register'",
                  "Menu entry 'Log in'", "Footer link 'About us'", "Footer link 'Contact us'",
                  "Footer link 'Privacy notice'", "Footer link 'Sitemap'"):
        assert any(t.startswith(entry) for t in titles), entry
    desktops = flow(run, "Menu entry 'Desktops'")
    taps = [s["locator"]["value"] for s in desktops["steps"] if s["action"] == "tap"]
    assert taps == ["div.menu-toggle", "div.sublist-toggle", 'a[href="/desktops"]']  # as a user reaches it
    assert desktops["steps"][-2:] == [{**desktops["steps"][-2], "action": "assert_screen", "value": "Shop. Desktops"},
                                      {**desktops["steps"][-1], "action": "assert_text", "value": "Desktops"}]


def test_links_to_other_websites_are_listed_but_never_followed(run):
    row = next(r for r in run["rows"] if r["name"] == "'Facebook'")
    assert row["status"] == "not tested" and "another website" in row["reason"]
    assert "Facebook" not in run["shop"].pressed


def test_each_page_is_recorded_once_with_a_screenshot_and_opened_by_its_address(run):
    screens = run["result"]["screens"]
    routes = [s["web_url"].split(BASE)[1].split("?")[0] for s in screens]
    assert len(routes) == len(set(routes))
    for route in ("/", "/computers", "/desktops", "/books", "/about-us", "/contactus", "/privacy", "/sitemap",
                  "/register", "/login", "/cart", "/laptop-pro"):
        assert route in routes, route
    assert all(s["screenshot"] and (run["dir"] / s["screenshot"]).is_file() for s in screens)
    assert all(s.get("open_by_url") for s in screens)
    assert not any("checkout" in route for route in routes)


# ------------------------------------------------------------------ 3. every page to its end

def test_every_page_is_read_to_its_end_and_controls_below_the_screen_say_how_to_reach_them(run):
    product = next(s for s in run["result"]["screens"] if s["web_url"].endswith("/laptop-pro"))
    reviews = next(e for e in product["elements"] if e.get("text") == "Read the reviews")
    assert reviews["web_below_fold"] and reviews["how_to_reach"].startswith("scroll down about")
    add = next(e for e in product["elements"] if e.get("text") == "Add to cart")
    assert add["how_to_reach"] == "on the first screen" and not add["web_below_fold"]
    read = [r for r in run["rows"] if r["area"] == "page"]
    assert len(read) == len(run["result"]["screens"]) and all(r["status"] == "passed" for r in read)
    # The tap on a control below the fold scrolls to it first, like a user
    review_flow = flow(run, "Tap 'Read the reviews'")
    assert [s["action"] for s in review_flow["steps"]][:3] == ["open", "scroll_to", "tap"]


# ------------------------------------------------------------------ 4. every feature, each from a fresh visit

def test_the_cart_really_adds_counts_lists_updates_and_removes(run):
    titles = run["titles"]
    assert "Add 'Laptop Pro' to the cart: the message 'The product has been added to your cart' appears, " \
           "'(0)' changes to '(1)'" in titles
    assert any(t.startswith("Add 2 of 'Laptop Pro' to the cart") and "'(0)' changes to '(2)'" in t for t in titles)
    assert "The cart lists 'Laptop Pro' after Add to cart" in titles
    assert any(t.startswith("Change the quantity of 'Laptop Pro' in the cart to 2") and "'$1200' changes to '$2400'" in t
               for t in titles)
    assert any(t.startswith("Remove 'Laptop Pro' from the cart") and "'Your Shopping Cart is empty!' appears" in t
               for t in titles)
    remove = flow(run, "Remove 'Laptop Pro'")
    assert remove["steps"][-1]["action"] in ("assert_text", "assert_not_visible", "assert_visible")


def test_a_javascript_alert_after_add_to_cart_is_checked_and_closed(run):
    add = flow(run, "Add 'Laptop Pro' to the cart")
    actions = [s["action"] for s in add["steps"]]
    alert = add["steps"][actions.index("assert_alert")]
    assert alert["value"] == "The product has been added to your cart"
    assert actions.index("assert_alert") == actions.index("tap") + 1  # checked right after the tap
    assert run["shop"].alert is None


def test_checkout_place_order_and_checkout_links_are_never_pressed_and_say_why(run):
    pressed = " ".join(run["shop"].pressed).casefold()
    assert "checkout" not in pressed and "place order" not in pressed
    for label in ("'Checkout'", "'Place order'", "'Go to checkout'"):
        row = next(r for r in run["rows"] if r["name"] == label)
        assert row["status"] == "not tested" and "checkout" in row["reason"]
    steps = [s for item in run["result"]["auto_flows"] for s in item["flow"]["steps"]]
    assert not any("checkout" in json.dumps(s).casefold() or "place-order" in json.dumps(s) for s in steps)


def test_register_then_login_with_that_account_explore_behind_login_and_log_out(run):
    titles = run["titles"]
    assert "Sign-up with valid details succeeds on Shop. Register — /register" in titles
    assert "Login with empty fields is refused: 'Please enter your email' appears" in titles
    assert "Login with a wrong password is refused: 'Login was unsuccessful.' appears" in titles
    assert "Login with the account it just registered succeeds" in titles
    assert any(t.startswith("After logging in, 'My account': 'Shop. Customer info' opens") for t in titles)
    assert any(t.startswith("After logging in, 'My account' > 'Orders'") for t in titles)
    assert "Log out with 'Log out': 'Log in' appears" in titles
    signup = flow(run, "Sign-up with valid details")
    emails = [s for s in signup["steps"] if s.get("secret_ref") == "BLOWAI_SECRET_AUTO_SIGNUP_EMAIL"]
    assert emails and all("value" not in s or s["value"] is None for s in emails)


def test_the_registered_account_is_kept_only_in_the_private_folder(run):
    saved = json.loads((run["dir"] / ".private" / "auto_secrets.json").read_text(encoding="utf-8"))
    email = saved["BLOWAI_SECRET_AUTO_ACCOUNT_USERNAME"]
    assert email.endswith("@example.com") and email in run["shop"].accounts
    for public in ("screens.json", "android_discovery.json", "android_interaction.json", "auto_flows.json"):
        assert email not in (run["dir"] / public).read_text(encoding="utf-8"), public
    login = flow(run, "Login with the account it just registered")
    refs = {s.get("secret_ref") for s in login["steps"]}
    assert {"BLOWAI_SECRET_AUTO_ACCOUNT_USERNAME", "BLOWAI_SECRET_AUTO_ACCOUNT_PASSWORD"} <= refs


def test_search_sort_contact_form_newsletter_wishlist_and_a_product(run):
    titles = run["titles"]
    assert "Search for 'Laptop' on Shop. Home — / shows results" in titles
    assert any(t.startswith("Choose 'Name: A to Z' in 'Sort by'") for t in titles)
    sort = flow(run, "Choose 'Name: A to Z'")
    assert {"action": "assert_text", "value": "Name: A to Z",
            "locator": {"strategy": "css", "value": "#orderby option:checked"}}.items() <= \
        next(s for s in sort["steps"] if "option:checked" in json.dumps(s)).items()
    assert "Contact form with valid details succeeds on Shop. Contact Us — /contactus" in titles
    assert any(t.startswith("An invalid email ('qa.tester') in 'Your email' is refused") for t in titles)
    assert "Newsletter sign-up with valid details succeeds on Shop. Home — /" in titles
    assert any(t.startswith("Tap 'Add to wishlist'") and "'Wishlist (0)' changes to 'Wishlist (1)'" in t
               for t in titles)
    assert any(t.startswith("Tap 'Desk Lamp' on Shop. Home") for t in titles)  # one product card stands for all


def test_every_check_starts_from_a_fresh_visit_but_keeps_the_bot_check_pass(run):
    shop = run["shop"]
    assert shop.resets >= run["result"]["interaction"]["tries_used"]  # cookies cleared before each try / replay
    assert "cf_clearance" in shop.cookies and shop.storage == {}


def test_flows_never_leave_the_approved_website(run):
    contract = json.loads((run["dir"] / ".private" / "auto_contract.json").read_text(encoding="utf-8"))
    assert contract["test_mode"] and contract["allowed_origins"] == [origin(BASE)]
    opened = [s["value"] for f in contract["flows"] for s in f["steps"] if s["action"] == "open"]
    assert opened and all(guard_url(url, CONFIG) is None for url in opened)
    parse_contract(contract)  # still valid as a whole


# ------------------------------------------------------------------ 5. no silent gaps: the coverage list and report

def test_every_planned_check_has_a_result_and_a_plain_reason(run):
    rows = run["rows"]
    assert rows and all(r["status"] in ("passed", "failed", "not tested") and r["reason"] for r in rows)
    named = {r["name"] for r in rows}
    for title in run["titles"]:
        assert title[:180] in named
    assert any(r["area"] == "phone" and r["status"] == "not tested" for r in rows)


def test_kept_flows_become_tests_and_the_report_lists_every_result(run, tmp_path):
    from backend.android_reporting import render_mobile_report, user_coverage
    result = run["result"]
    state = {**result, "run_dir": str(run["dir"]), "run_id": "r"}
    designed = android_pipeline.test_design_agent(state)
    cases = [c for c in designed["test_cases"] if c.get("auto_flow_id")]
    assert len(cases) == len(result["auto_flows"])
    scripts = android_pipeline.script_generator_agent({**state, **designed})
    assert scripts["scripts"]
    # The final run: one flow failed with a screenshot, one was not run, the rest passed
    results = [{"id": c["id"], "outcome": "passed", "checks": 1, "auto_flow_id": c["auto_flow_id"]} for c in cases]
    results[0].update(outcome="failed", error="AssertionError: Expected text '(1)'; found '(0)'.",
                      screenshot="screenshots/android_x.png")
    results.pop()
    covered = user_coverage(result["interaction"], cases, results)
    first = next(r for r in covered["rows"] if r.get("flow_id") == cases[0]["auto_flow_id"])
    assert first["status"] == "failed" and first["reason"].startswith("AssertionError") and first["screenshot"]
    last = next(r for r in covered["rows"] if r.get("flow_id") == cases[-1]["auto_flow_id"])
    assert last["status"] == "not tested"
    assert sum(covered["counts"].values()) == len(covered["rows"])
    summary = {"counts": {"passed": 1, "failed": 1, "error": 0}, "verdict": "Not Ready", "screens_visited": 1,
               "self_healing_attempts": 0, "reasons": [], "gates": [], "coverage": {"tested": 1, "unvisited": []},
               "package_name": "com.android.chrome", "android_version": "16", "device_id": "emulator-5554",
               "run_id": "r", "interaction": {**result["interaction"], "kept": len(cases)},
               "user_like_tests": {"total": len(cases), "passed": 1, "failed": 1}, "app_crashes": 0,
               "user_like_coverage": covered, "bot_check": result["bot_check"]}
    page = render_mobile_report(summary, [], [], [], result["screens"], [])
    assert "What was tested" in page and "Tested - failed" in page and "Not tested" in page
    assert 'href="screenshots/android_x.png"' in page and "test website" in page


def test_a_run_that_runs_out_of_tries_lists_every_check_it_did_not_reach(tmp_path):
    result = explore(tmp_path, FakeShop(), max_interactions=12)
    interaction = result["interaction"]
    assert interaction["stopped"] == "User-like test limit reached"
    unreached = [r for r in interaction["coverage"] if "limit of user-like tries" in r["reason"]]
    assert unreached and all(r["status"] == "not tested" for r in unreached)
    assert all(t["flow"]["title"].startswith(("Open the menu", "Menu entry")) for t in result["auto_flows"])


def test_without_test_mode_a_website_is_only_explored_safely(tmp_path):
    shop = FakeShop()
    result = explore(tmp_path, shop, interaction_testing=False)
    assert result["auto_flows"] == [] and not result["interaction"]
    # Pay-only never-press: cart/register/login may be opened in discovery; checkout must stay out.
    assert not any("checkout" in p.casefold() or "place order" in p.casefold() for p in shop.pressed)
