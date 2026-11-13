"""Tests for the tester itself:  python -m pytest tests -q"""
import pytest

from backend.agents.change_detection import diff_pages, page_key
from backend.agents.discovery import _mode, _normalize, _same_app
from backend.agents.script_generator import validate_script
from backend.agents.self_healing import _find_new_selector, _find_old_element, _safe_repair

GOOD = "import re\nfrom playwright.sync_api import expect\n\ndef test_a(page):\n    page.goto('x')\n    assert page.title()\n"


def test_validate_accepts_good_script():
    assert validate_script(GOOD) is None


def test_validate_blocks_dangerous_code():
    assert "Banned import" in validate_script("import os\ndef test_a(page):\n    pass\n")
    assert "Banned call" in validate_script("def test_a(page):\n    eval('1')\n")


def test_healing_cannot_remove_assertions():
    weakened = GOOD.replace("    assert page.title()\n", "    pass\n")
    assert "assertions removed" in _safe_repair(GOOD, weakened)


def test_page_key_ignores_host_and_port():
    assert page_key("http://localhost:3000/login/") == page_key("http://127.0.0.1:5173/login")


def test_diff_detects_changed_button():
    old = {"title": "Login", "buttons": [{"text": "Login", "selector": "#login-btn"}]}
    new = {"title": "Login", "buttons": [{"text": "Login", "selector": "#signin"}]}
    d = diff_pages(old, new)
    assert any("removed" in x for x in d) and any("added" in x for x in d)


def test_mode_is_decided_from_the_link():
    mode = lambda url: _mode(_normalize(url))  # noqa: E731
    assert mode("https://shop.test") == ("site", "")
    assert mode("https://shop.test/index.html") == ("site", "")
    assert mode("https://rahulshettyacademy.com/seleniumPractise/#/") == ("section", "/seleniumPractise")
    assert mode("https://shop.test/login") == ("site", "")  # a login page is the door to the whole app
    assert mode("https://eventhub.rahulshettyacademy.com/login") == ("site", "")
    assert mode("https://shop.test/blog/my-post")[0] == "page"
    assert mode("https://shop.test/item?id=5")[0] == "page"
    assert mode("https://shop.test/contact.html")[0] == "page"
    assert mode("https://shop.test/app/#/cart")[0] == "page"
    # register / login pages (also inside a single-page app) -> the whole app they belong to
    assert mode("https://rahulshettyacademy.com/client/#/auth/register") == ("section", "/client")
    assert mode("https://rahulshettyacademy.com/client/#/auth/login") == ("section", "/client")
    assert mode("https://shop.test/auth/register") == ("site", "")
    assert mode("https://shop.test/app/signup") == ("section", "/app")
    assert mode("https://shop.test/users")[0] == "section"  # not a login page


def test_same_app_by_title_name():
    login = {"url": "https://shop.test/login", "title": "Login - MyShop", "links": []}
    assert _same_app({"url": "https://shop.test/orders", "title": "Orders - MyShop", "links": []}, login, "shop.test")
    assert not _same_app({"url": "https://shop.test/blog", "title": "Our Blog", "links": []}, login, "shop.test")


GREENKART = {  # the shape discovery.py records for rahulshettyacademy.com/seleniumPractise
    "url": "https://rahulshettyacademy.com/seleniumPractise", "slug": "seleniumPractise", "title": "GreenKart",
    "itemNames": ["Brocolli - 1 Kg", "Cauliflower - 1 Kg"], "links": [], "forms": [],
    "inputs": [{"tag": "input", "type": "search", "name": "", "id": "", "label": "Search for Vegetables and Fruits",
                "placeholder": "Search for Vegetables and Fruits",
                "selector": 'input[placeholder="Search for Vegetables and Fruits"]'},
               {"tag": "input", "type": "number", "name": "", "id": "", "label": "", "placeholder": "",
                "selector": "input.quantity"}],
    "buttons": [{"text": "ADD TO CART", "selector": 'button:has-text("ADD TO CART")', "type": "button", "count": 30},
                {"text": "+", "selector": "a.increment", "tag": "a", "count": 30},
                {"text": "–", "selector": "a.decrement", "tag": "a", "count": 30},
                {"text": "cart icon", "selector": "a.cart-icon", "tag": "a", "count": 1},
                {"text": "PROCEED TO CHECKOUT", "selector": "button.disabled", "disabled": True, "count": 1},
                {"text": "BUY NOW", "selector": 'button:has-text("BUY NOW")', "count": 1}],
}


def test_features_found_and_checkout_never_clicked():
    from backend.agents.script_generator import template_script
    from backend.agents.test_design import features, rule_based_cases, safe_buttons
    f = features(GREENKART)
    assert f["search"].startswith("input[placeholder") and f["word"] == "Brocolli"
    assert f["add"] == 'button:has-text("ADD TO CART")' and f["items"] == f["add"]
    assert (f["qty"], f["plus"], f["minus"]) == ("input.quantity", "a.increment", "a.decrement")
    clicked = {b["text"] for b in safe_buttons(GREENKART)}
    assert "BUY NOW" not in clicked and "PROCEED TO CHECKOUT" not in clicked and "ADD TO CART" in clicked
    cases = rule_based_cases(GREENKART)
    ids = {c["id"] for c in cases}
    assert {"search_finds_item", "search_no_results", "add_to_cart", "quantity_plus_minus"} <= ids
    code = template_script(GREENKART, cases)
    assert validate_script(code) is None
    for cid in ("search_finds_item", "search_no_results", "add_to_cart", "quantity_plus_minus"):
        assert f"def test_{cid}(" in code


FLIGHTS = {  # the shape discovery.py records for rahulshettyacademy.com/dropdownsPractise
    "url": "https://rahulshettyacademy.com/dropdownsPractise", "slug": "dropdownsPractise", "title": "QAClickJet",
    "links": [], "forms": [], "itemNames": [],
    "inputs": [
        {"tag": "input", "type": "radio", "name": "trip", "label": "One Way", "selector": "#trip_0"},
        {"tag": "input", "type": "radio", "name": "trip", "label": "Round Trip", "selector": "#trip_1"},
        {"tag": "input", "type": "text", "label": "DEPART DATE", "selector": "#date1", "readonly": True, "opener": True},
        {"tag": "input", "type": "text", "label": "Type to Select", "selector": "#autosuggest", "opener": True, "suggests": True},
        {"tag": "select", "type": "select-one", "label": "CURRENCY", "selector": "#currency",
         "options": [{"value": "INR", "text": "INR"}, {"value": "USD", "text": "USD"}]},
        {"tag": "input", "type": "checkbox", "label": "Senior Citizen", "selector": "#senior"},
    ],
    "buttons": [{"text": "1 Adult", "selector": "#divpaxinfo", "tag": "div", "opener": True, "custom": True, "count": 1},
                {"text": "Flights", "selector": 'a[title="Flights"]', "tag": "a", "opener": True, "count": 1}],
}


def test_every_control_gets_its_own_test():
    from backend.agents.script_generator import template_script
    from backend.agents.test_design import data_cases, rule_based_cases
    cases = rule_based_cases(FLIGHTS)
    kinds = {c["id"]: c.get("kind") for c in cases}
    assert kinds["dropdown_currency"] == "dropdown"
    assert kinds["choice_one_way"] == "radio"
    assert kinds["checkbox_senior_citizen"] == "checkbox"
    assert {"opens_depart_date", "opens_type_to_select", "opens_1_adult"} <= set(kinds)
    assert not any("flights" in k for k in kinds)  # a menu link is clicked, not expected to "open" something
    assert not any(c["selector"] == "#date1" for c in data_cases(FLIGHTS))  # read-only box: no typing tests
    code = template_script(FLIGHTS, cases)
    assert validate_script(code) is None
    for cid in kinds:
        if cid != "buttons_click":
            assert f"def test_{cid}(" in code


def test_input_robustness_cases_are_opt_in(monkeypatch):
    from backend.agents.test_design import data_cases, rule_based_cases
    from backend.config import settings

    page = {"url": "https://shop.test", "slug": "home", "inputs": [
        {"tag": "input", "type": "search", "label": "Search", "selector": "#search", "maxlength": 10},
    ]}
    monkeypatch.setattr(settings, "data_tests", False)
    assert data_cases(page) == []
    assert not any(case["id"].startswith("maxlength_") for case in rule_based_cases(page))


def test_more_control_kinds_and_coverage_list():
    from backend.agents.script_generator import template_script
    from backend.agents.test_design import coverage, rule_based_cases
    page = {"url": "https://x.test/p", "slug": "p", "title": "Demo", "links": [], "itemNames": [],
            "inputs": [{"tag": "input", "type": "range", "label": "Volume", "selector": "#vol"},
                       {"tag": "input", "type": "file", "label": "Photo", "selector": "#photo"}],
            "forms": [{"index": 0, "selector": "#login", "submit": {"text": "Login", "selector": "#go"},
                       "fields": [{"type": "text", "selector": "#user", "required": True, "label": "User"},
                                  {"type": "password", "selector": "#pw", "required": True, "label": "Password"}]}],
            "buttons": [{"text": "Home", "selector": "#t1", "kind": "tab"}, {"text": "Profile", "selector": "#t2", "kind": "tab"},
                        {"text": "Open dialog", "selector": "#m", "kind": "modal"},
                        {"text": "Click for JS Confirm", "selector": "#c", "kind": "dialog"},
                        {"text": "Delete account", "selector": "#del"}],
            "draggables": [{"text": "A", "selector": "#a"}, {"text": "B", "selector": "#b"}],
            "hovers": [{"text": "Menu", "selector": "#menu"}]}
    cases = rule_based_cases(page)
    kinds = {c.get("kind") for c in cases}
    assert {"tabs", "modal", "dialog", "slider", "upload", "drag", "hover", "login_wrong"} <= kinds
    code = template_script(page, cases)
    assert validate_script(code) is None
    cov = coverage(page, code)  # tested = really used by the generated test code
    not_tested = {i["name"]: i["reason"] for i in cov["items"] if i["status"] != "tested"}
    assert list(not_tested) == ["Delete account"] and "on purpose" in not_tested["Delete account"]
    scripted = [i for i in cov["items"] if i["status"] == "tested"]
    assert scripted and all(i.get("meaning") == "scripted" for i in scripted)
    assert cov.get("notes") and "business-verified" in cov["notes"][0]


def test_every_step_is_its_own_focused_test_case():
    """Each thing a person can do on a page is ONE test case with its own result (they were bundled into one large
    case per page before: one failing step failed the case, and every feature in it was reported failed). A control
    that is on several pages (a header menu) is tested once."""
    from backend.agents.script_generator import checks_script, site_script, steps_module
    from backend.agents.test_design import builtin_checks, login_form, page_steps, small_checks
    login = {"url": "https://x.test/login", "slug": "login", "title": "Login", "links": [], "itemNames": [], "inputs": [],
             "buttons": [], "forms": [{"index": 0, "selector": "#f", "submit": {"text": "Sign in", "selector": "#go"},
                                       "fields": [{"type": "email", "selector": "#user", "label": "Email"},
                                                  {"type": "password", "selector": "#pw", "label": "Password"}]}]}
    assert login_form(login) == {"user": "#user", "password": "#pw", "submit": "#go", "form": "#f", "openers": []}
    menu = {"text": "Account", "name": "Account", "selector": 'li.dropdown:has-text("Account")'}  # (a header menu)
    pages = [dict(GREENKART, auth=True, hovers=[menu]), dict(FLIGHTS, auth=True, hovers=[menu]), login]
    checks = builtin_checks(pages)
    small = small_checks(pages, [])
    assert len(small) == 5 and all(c["size"] == "small" for c in small)
    assert checks and all(c["kind"] == "check" and len(c["parts"]) == 1 and len(c["tests"]) == 1 for c in checks)
    assert all(c["feature"] and c["expected"] and c["steps"] for c in checks)
    used = {(c["parts"][0]["page"], c["parts"][0]["step"]["id"]) for c in checks}
    for p in pages:  # every step of every page is its own check - the shared menu once (on the first page)
        for s in page_steps(p):
            assert ((p["slug"], s["id"]) in used) == (s.get("kind") != "hover" or p is pages[0]), (p["slug"], s["id"])
    assert len([c for c in checks if c["parts"][0]["step"].get("kind") == "hover"]) == 1
    assert next(c for c in checks if c["pages"] == ["login"])["guest"]  # login page: tested as a visitor
    modules = {}
    for p in pages:
        code = steps_module(p, [c["parts"][0]["step"] for c in checks if c["parts"][0]["page"] == p["slug"]])
        assert validate_script(code, need_tests=False) is None and "def test_" not in code
        modules[p["slug"]] = code
    code, missing = checks_script(checks, modules)
    assert validate_script(code) is None and not missing
    assert all(f"def test_{c['id']}(" in code for c in checks) and "run_steps" not in code
    assert validate_script(site_script(pages)) is None


def test_real_journeys_without_ai(monkeypatch):
    from backend.agents.script_generator import journeys_script
    from backend.agents.test_design import builtin_journeys, settings
    monkeypatch.setattr(settings, "test_username", "qa@example.com")
    monkeypatch.setattr(settings, "test_password", "secret")
    login = {"url": "https://shop.test/login", "slug": "login", "title": "Login - Shop", "itemNames": [], "inputs": [],
             "buttons": [], "links": [{"href": "https://shop.test/register", "text": "Register"}],
             "forms": [{"index": 0, "selector": "#f", "submit": {"text": "Sign in", "selector": "#go"},
                        "fields": [{"type": "email", "selector": "#user", "label": "Email"},
                                   {"type": "password", "selector": "#pw", "label": "Password"}]}]}
    register = {"url": "https://shop.test/register", "slug": "register", "title": "Register - Shop", "itemNames": [],
                "buttons": [], "links": [{"href": "https://shop.test/login", "text": "Login"}],
                "inputs": [{"tag": "input", "type": "text", "label": "First Name", "selector": "#first"},
                           {"tag": "input", "type": "email", "label": "Email", "selector": "#email"},
                           {"tag": "select", "type": "select-one", "label": "Occupation", "selector": "#job",
                            "options": [{"value": "1", "text": "Doctor"}]},
                           {"tag": "input", "type": "radio", "name": "g", "label": "Male", "selector": "#m"},
                           {"tag": "input", "type": "radio", "name": "g", "label": "Female", "selector": "#f2"},
                           {"tag": "input", "type": "date", "label": "Birthday", "selector": "#bd", "readonly": True}],
                "forms": [{"index": 0, "selector": "#reg", "submit": {"text": "Register", "selector": "#r"},
                           "fields": [{"type": "text", "selector": "#first"}, {"type": "email", "selector": "#email"},
                                      {"type": "select-one", "selector": "#job"}, {"type": "radio", "selector": "#m"},
                                      {"type": "radio", "selector": "#f2"}, {"type": "text", "selector": "#bd"}]}]}
    shop = dict(GREENKART, url="https://shop.test/", slug="home", auth=True, final_url="https://shop.test/",
                links=[{"href": "https://shop.test/orders", "text": "Orders"}, {"href": "https://shop.test/deals", "text": "Deals"}])
    orders = {"url": "https://shop.test/orders", "slug": "orders", "title": "Orders", "auth": True, "links": [],
              "inputs": [], "buttons": [], "forms": [], "itemNames": []}
    deals = dict(orders, url="https://shop.test/deals", slug="deals", title="Deals")
    journeys = builtin_journeys([login, register, shop, orders, deals])
    kinds = [j["journey"] for j in journeys]
    assert kinds[:2] == ["login", "shop"] and "form" in kinds and "navigate" in kinds
    shop_j = next(j for j in journeys if j["journey"] == "shop")
    assert shop_j["spec"]["word"] == "Brocolli" and shop_j["spec"]["cart"] == "a.cart-icon"  # never checkout / buy
    form_j = next(j for j in journeys if j["journey"] == "form")
    filled = {f["selector"]: f["kind"] for f in form_j["spec"]["fields"]}
    assert filled == {"#first": "type", "#email": "type", "#job": "select", "#m": "radio"}  # one radio per group, no read-only date
    nav = next(j for j in journeys if j["journey"] == "navigate" and j["spec"]["logged_in"])
    assert [l["text"] for l in nav["spec"]["links"]] == ["Orders", "Deals"] and not nav["guest"]
    assert next(j for j in journeys if j["journey"] == "login")["guest"]  # logging in starts as a visitor
    code = journeys_script(journeys)
    assert validate_script(code) is None
    assert all(f"def test_journey_{n}(" in code for n in range(1, len(journeys) + 1))
    assert "secret" not in code and "qa@example.com" not in code  # the password is never written into the code


def test_one_page_site_menu_and_section_links():
    from backend.agents.script_generator import all_links_script, journeys_script
    from backend.agents.test_design import builtin_journeys, section_links
    home = {"url": "https://site.test", "slug": "home", "title": "Site", "inputs": [], "buttons": [], "forms": [],
            "itemNames": [], "links": [{"href": "https://site.test/projects/p1", "text": "View details"}],
            "sections": [{"href": "https://site.test/#projects", "section": "projects", "text": "Projects", "nav": True,
                          "visible": True, "exists": True},
                         {"href": "https://site.test/#plots", "section": "plots", "text": "Availability", "nav": True,
                          "visible": True, "exists": False},
                         {"href": "https://site.test/#enquiry", "section": "enquiry", "text": "Book a site visit",
                          "nav": False, "visible": True, "exists": True}]}
    p1 = {"url": "https://site.test/projects/p1", "slug": "projects_p1", "title": "P1", "inputs": [], "buttons": [],
          "forms": [], "itemNames": [], "links": [],
          "sections": [{"href": "https://site.test/#projects", "section": "projects", "text": "Projects", "nav": True,
                        "visible": True, "exists": None}]}
    secs = section_links([home, p1])
    assert [(s["page"], s["section"]) for s in secs] == [("https://site.test/", "projects"), ("https://site.test/", "plots"),
                                                         ("https://site.test/", "enquiry")]
    code, n = all_links_script([home, p1])
    assert validate_script(code) is None and n == 1 + 3 and "def test_section_link(" in code
    nav = next(j for j in builtin_journeys([home, p1]) if j["journey"] == "navigate")
    assert [l.get("section", "page") for l in nav["spec"]["links"]] == ["page", "projects", "plots", "enquiry"]
    assert validate_script(journeys_script([nav])) is None


def test_test_account_signup_page_and_login_name():
    from backend.agents.discovery import _login_name, _signup_url
    login_page = {"links": [{"href": "https://shop.test/forgot-password", "text": "Forgot password?"},
                            {"href": "https://shop.test/account/register", "text": "Create an account"},
                            {"href": "https://other.test/register", "text": "Register"}]}
    assert _signup_url(login_page, "https://shop.test/login") == "https://shop.test/account/register"
    assert _signup_url({"links": []}, "https://x.test/client/#/auth/register") == "https://x.test/client/#/auth/register"
    assert _signup_url({"links": [{"href": "https://shop.test/about", "text": "About"}]}, "https://shop.test/login") is None
    account = {"username": "agentic.qa.1@example.com", "email": "agentic.qa.1@example.com", "user_name": "agenticqa1",
               "password": "x"}
    form = {"user": "#u", "password": "#p", "submit": "#s"}
    by_email = {"inputs": [{"selector": "#u", "type": "email", "label": "Email"}]}
    by_name = {"inputs": [{"selector": "#u", "type": "text", "label": "Username"}]}
    assert _login_name(by_email, form, account) == "agentic.qa.1@example.com"
    assert _login_name(by_name, form, account) == "agenticqa1"


def test_end_to_end_runs_first_links_last():
    from backend.excel import file_rank
    files = ["test_all_links.py", "test_login_data.py", "test_site.py", "test_checks.py", "test_journeys.py",
             "test_flows_ai.py"]
    assert sorted(files, key=file_rank) == ["test_journeys.py", "test_checks.py", "test_flows_ai.py", "test_site.py",
                                            "test_login_data.py", "test_all_links.py"]


def test_heal_finds_button_by_text():
    old_page = {"buttons": [{"text": "Login", "selector": "#login-btn"}]}
    new_page = {"buttons": [{"text": "Login", "selector": "#signin"}]}
    kind, el, form = _find_old_element("#login-btn", old_page)
    assert _find_new_selector(kind, el, form, new_page) == "#signin"


def test_every_built_in_test_file_passes_the_sandbox_checks():
    """The sandbox's static checks apply to OUR code too (a helper using getattr() once got the whole journeys file
    rejected - its tests never ran)."""
    from backend.agents.script_generator import features_script, journeys_script, learned_script
    learned = [{"id": "learned_1", "title": "'Next' shows another picture (Home)", "guest": True,
                "spec": {"url": "https://x.test/", "name": "Next", "selector": "a.carousel-control-next",
                         "action": "click", "value": None, "effect": "picture", "message": "", "tone": "", "to": "",
                         "revealed": [], "opener": None, "guest": True}}]
    assert validate_script(learned_script(learned)) is None
    feature = [{"id": "feature_1", "title": "'Next' shows other items (Shop)", "guest": False, "feature_kind": "pagination",
                "spec": {"url": "https://x.test/shop", "items": "div.card a[href]", "href": "", "selector": "#next2",
                         "name": "Next"}}]
    assert validate_script(features_script(feature)) is None
    product = [{"id": "journey_1", "title": "Shopping journey", "journey": "product", "guest": False,
                "spec": {"url": "https://x.test/shop", "search": "", "word": "", "items": "div.card a[href]",
                         "options": [], "add": "#add", "add_text": "Add to cart", "cart": "#cart", "cart_text": "Cart",
                         "guest": False, "change_cart": True}}]
    code = journeys_script(product)
    assert validate_script(code) is None and "_note(" in code


def test_a_selector_that_is_gone_is_found_on_the_same_page_of_the_last_run(tmp_path):
    """(was: healing looked for the OLD selector in the NEW pages, so a renamed id used by test_learned.py /
    test_features.py / test_journeys.py was never repaired)"""
    import json

    from backend.agents.self_healing import _moved_page
    old = {"url": "http://127.0.0.1:5000/deals", "slug": "deals", "auth": False, "inputs": [], "forms": [],
           "buttons": [{"text": "Notify me", "selector": "#notify"}]}
    (tmp_path / "app_map.json").write_text(json.dumps([old]), encoding="utf-8")
    new = dict(old, url="http://127.0.0.1:6000/deals", buttons=[{"text": "Notify me", "selector": "#notify-me"}])
    was, now = _moved_page("#notify", {"app_map": [new], "changes": {"baseline_dir": str(tmp_path)}})
    assert was == old and now is new  # (another port: the same page)
    kind, el, form = _find_old_element("#notify", was)
    assert _find_new_selector(kind, el, form, now) == "#notify-me"
    assert _moved_page("#nothing", {"app_map": [new], "changes": {"baseline_dir": str(tmp_path)}}) == (None, None)


def test_a_renamed_element_in_the_learned_tests_is_repaired_from_the_whole_error(tmp_path, monkeypatch):
    """The finding keeps only the error's last lines - after Playwright's page snapshot they don't name the element;
    the test's whole error does ('waiting for locator(...)'). The old selector is found on the last run's page."""
    import json

    from backend.agents import self_healing
    monkeypatch.setattr(self_healing, "llm_enabled", lambda: False)
    old = {"url": "http://127.0.0.1:5000/deals", "slug": "deals", "auth": False, "inputs": [], "forms": [],
           "buttons": [{"text": "Notify me", "selector": "#notify"}]}
    (tmp_path / "baseline").mkdir()
    (tmp_path / "baseline" / "app_map.json").write_text(json.dumps([old]), encoding="utf-8")
    tests = tmp_path / "generated_tests"
    tests.mkdir()
    code = ("import re\nimport pytest\nfrom playwright.sync_api import expect\n\n\n"
            "def test_learned_4(page, console_errors):\n    \"\"\"'Notify me' shows its message\"\"\"\n"
            "    L = {'url': 'http://127.0.0.1:5000/deals', 'name': 'Notify me', 'selector': '#notify'}\n"
            "    page.goto(L['url'])\n    expect(page.locator(L['selector']).first).to_be_visible()\n")
    (tests / "test_learned.py").write_text(code, encoding="utf-8")
    snapshot = "\n".join(f"E   - paragraph: line {n}" for n in range(12))
    whole = ("E   AssertionError: 'Notify me' should be visible\nE   Locator expected to be visible\n"
             "E   Error: element(s) not found\nE   Call log:\nE     - waiting for locator(\"#notify\").first\n"
             f"E   Aria snapshot:\n{snapshot}")
    nodeid = "test_learned.py::test_learned_4"
    out = self_healing.self_healing_agent({
        "run_dir": str(tmp_path), "changes": {"baseline_dir": str(tmp_path / "baseline")},
        "app_map": [dict(old, url="http://127.0.0.1:6000/deals", buttons=[{"text": "Notify me", "selector": "#notify-me"}])],
        "results": [{"nodeid": nodeid, "file": "test_learned.py", "test": "test_learned_4", "error": whole}],
        "failures": [{"source": "test", "category": "test_defect", "nodeid": nodeid, "file": "test_learned.py",
                      "test": "test_learned_4", "error": "\n".join(whole.splitlines()[-6:])}]})
    h = out["healing_log"][0]
    assert h["method"] == "selector-match" and (h["from"], h["to"]) == ("#notify", "#notify-me"), h
    assert "'#notify-me'" in (tests / "test_learned.py").read_text(encoding="utf-8")


def test_a_locator_that_matches_several_elements_is_narrowed_to_the_visible_one(tmp_path, monkeypatch):
    """demoblaze: the AI's `button[aria-label='Close']` matched the Close buttons of 4 popups (strict mode). Only HOW
    the element is found changes - what is checked stays - and the re-run decides whether the repair is kept."""
    from backend.agents import self_healing
    monkeypatch.setattr(self_healing, "llm_enabled", lambda: False)
    tests = tmp_path / "generated_tests"
    tests.mkdir()
    code = ("import re\nimport pytest\nfrom playwright.sync_api import expect\n\n\n@pytest.mark.guest\n"
            "def test_ai_flow_6(page):\n    \"\"\"User opens the About Us popup\"\"\"\n    page.goto('https://x.test')\n"
            "    page.locator(\"button[aria-label='Close']\").click()\n"
            "    expect(page.locator('#about')).to_be_hidden()\n")
    (tests / "test_flows_ai.py").write_text(code, encoding="utf-8")
    err = "Locator.click: Error: strict mode violation: locator(\"button[aria-label='Close']\") resolved to 4 elements:"
    out = self_healing.self_healing_agent({"run_dir": str(tmp_path), "app_map": [], "failures": [
        {"source": "test", "category": "test_defect", "nodeid": "test_flows_ai.py::test_ai_flow_6",
         "file": "test_flows_ai.py", "test": "test_ai_flow_6", "error": err}]})
    fixed = (tests / "test_flows_ai.py").read_text(encoding="utf-8")
    assert "button[aria-label='Close'] >> visible=true" in fixed and "to_be_hidden()" in fixed
    h = out["healing_log"][0]
    assert h["method"] == "unique-locator" and h["status"] == "pending" and (tmp_path / h["backup"]).exists()
    assert out["rerun_only"] == ["test_flows_ai.py::test_ai_flow_6"]


@pytest.mark.parametrize("rerun, broke, status", [
    ({"outcome": "passed"}, [], "healed"),
    # the script works now, and the test fails on its real check: kept - the real result is reported
    ({"outcome": "failed", "file": "test_learned.py", "error_type": "AssertionError",
      "error": "AssertionError: 'Notify me' showed no message (while exploring it said 'We will email you')"},
     [], "repaired"),
    # still a script problem: the repair did not help - undone
    ({"outcome": "failed", "file": "test_learned.py", "error": "Locator.click: Timeout 5000ms exceeded.\n"
                                                              "waiting for locator('#notify-me')"}, [], "reverted"),
    # it passes, but another test of the same file passed before and fails now: undone
    ({"outcome": "passed"}, ["test_learned.py::test_learned_3"], "reverted"),
    (None, [], "reverted"),  # it did not run again: never called repaired
])
def test_a_repair_is_judged_by_running_the_tests_again(rerun, broke, status):
    from backend.agents.executor import _repair_verdict
    assert _repair_verdict(rerun, broke)[0] == status
