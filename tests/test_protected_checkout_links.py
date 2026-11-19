"""Pay/checkout destinations are recorded as protected, even when the label says Continue."""
from backend.agents.test_design import (
    blocked_cases,
    builtin_journeys,
    coverage,
    learned_cases,
    rule_based_cases,
    safe_buttons,
)
from backend.features import page_features
from backend.registry import build, link_tests, record_outcomes


def test_cart_checkout_anchor_is_protected_feature():
    cart = {
        "url": "http://127.0.0.1/index.php?rt=checkout/cart",
        "title": "Shopping Cart",
        "slug": "cart",
        "auth": False,
        "buttons": [{"text": "Update", "selector": "#cart_update", "disabled": False}],
        "links": [
            {"href": "http://127.0.0.1/index.php?rt=checkout/checkout", "text": "Checkout",
             "external": False, "chrome": True},
            {"href": "http://127.0.0.1/index.php?rt=account/invoice", "text": "Check Your Order",
             "external": False, "chrome": True},
        ],
        "inputs": [],
    }
    protected = next(f for f in page_features(cart) if f["kind"] == "protected")
    texts = {a["text"] for a in protected["actions"]}
    assert "Checkout" in texts
    assert "Check Your Order" not in texts
    titles = [c["title"] for c in blocked_cases([cart])]
    assert any("Checkout" in t and "not run" in t for t in titles)


def test_continue_that_opens_checkout_is_not_planned_as_a_click():
    page = {
        "url": "https://shop.example/cart",
        "title": "Cart",
        "slug": "cart",
        "auth": False,
        "buttons": [
            {"text": "Continue", "selector": "#go", "form_action": "/checkout", "role": "button"},
            {"text": "Details", "selector": "#details", "role": "button"},
        ],
        "links": [
            {"href": "https://shop.example/checkout", "text": "Continue", "external": False},
            {"href": "https://shop.example/index.php?rt=checkout/cart", "text": "Cart", "external": False},
        ],
        "forms": [{
            "index": 0, "selector": "#pay", "action": "/checkout",
            "fields": [{"name": "card", "type": "text", "selector": "#card", "required": True, "label": "Card"}],
            "submit": {"text": "Continue", "selector": "#go"},
        }],
        "inputs": [],
        "behaviour": [{"control": "Continue", "selector": "#go", "effect": "navigates",
                       "to": "https://shop.example/checkout", "action": "click"}],
    }
    protected = next(f for f in page_features(page) if f["kind"] == "protected")
    assert "Continue" in {a["text"] for a in protected["actions"]}
    assert "Continue" not in {b["text"] for b in safe_buttons(page)}
    assert "Details" in {b["text"] for b in safe_buttons(page)}
    cases = rule_based_cases(page)
    assert not any("submitting it empty" in c["title"] for c in cases)
    assert any("Continue" in c["title"] and c.get("blocked") for c in blocked_cases([page]))
    assert learned_cases([page]) == []
    row = next(item for item in coverage(page, "")["items"] if item["name"] == "Continue")
    assert row["status"] == "not tested" and "checkout" in row["reason"]

    reg = build([page], {})
    control = next(f for f in reg["features"].values() if f["name"] == "Continue" and f["level"] == "control")
    assert control["status"] == "blocked"
    link_tests(reg, [{
        "tc_id": "TC-1", "title": "Every button can be clicked", "pages": ["cart"],
        "parts": [{"page": "cart", "step": {"id": "buttons_click"}}],
        "execution_status": "Passed",
    }])
    record_outcomes(reg, [{
        "tc_id": "TC-1", "title": "Every button can be clicked", "pages": ["cart"],
        "parts": [{"page": "cart", "step": {"id": "buttons_click"}}],
        "execution_status": "Passed",
    }])
    assert reg["features"][control["id"]]["status"] == "blocked"
    clicked = {t["how"] for t in reg["features"][control["id"]]["tests"]}
    assert "clicks" not in clicked


def test_a_menu_journey_does_not_open_a_checkout_step():
    home = {
        "url": "https://shop.example/index.php?rt=common/home",
        "title": "Home", "slug": "home", "auth": False,
        "links": [
            {"href": "https://shop.example/index.php?rt=checkout/checkout", "text": "Continue", "visible": True},
            {"href": "https://shop.example/index.php?rt=product/category", "text": "Shop", "visible": True},
            {"href": "https://shop.example/index.php?rt=account/login", "text": "Login", "visible": True},
        ],
        "buttons": [], "inputs": [],
        "forms": [
            {"selector": "#contact", "action": "index.php?rt=content/contact",
             "fields": [
                 {"name": "first", "label": "First", "type": "text", "selector": "#first"},
                 {"name": "email", "label": "Email", "type": "email", "selector": "#email"},
                 {"name": "note", "label": "Note", "type": "text", "selector": "#note"},
             ],
             "submit": {"text": "Send", "selector": "#send"}},
            {"selector": "#pay", "action": "index.php?rt=checkout/confirm",
             "fields": [
                 {"name": "card", "label": "Card", "type": "text", "selector": "#card"},
                 {"name": "name", "label": "Name", "type": "text", "selector": "#name"},
                 {"name": "expiry", "label": "Expiry", "type": "text", "selector": "#exp"},
             ],
             "submit": {"text": "Continue", "selector": "#go"}},
        ],
    }
    shop = {"url": "https://shop.example/index.php?rt=product/category", "title": "Shop", "slug": "shop",
            "auth": False, "links": [], "buttons": [], "forms": [], "inputs": []}
    login = {"url": "https://shop.example/index.php?rt=account/login", "title": "Login", "slug": "login",
             "auth": False, "links": [], "buttons": [], "forms": [], "inputs": []}
    checkout = {"url": "https://shop.example/index.php?rt=checkout/checkout", "title": "Checkout", "slug": "pay",
                "auth": False, "links": [], "buttons": [], "forms": [], "inputs": []}
    journeys = builtin_journeys([home, shop, login, checkout], limit=20)
    menu = next(j for j in journeys if j["journey"] == "navigate")
    assert [link["text"] for link in menu["spec"]["links"]] == ["Shop", "Login"]
    forms = [j for j in journeys if j["journey"] == "form"]
    assert [j["spec"]["form"] for j in forms] == ["#contact"]


def test_a_recorded_checkout_page_is_not_given_a_test_that_opens_it(tmp_path, monkeypatch):
    from backend.agents.test_design import test_design_agent
    from backend.config import settings

    monkeypatch.setattr(settings, "reuse_tests", False)
    monkeypatch.setattr(settings, "incremental", False)
    monkeypatch.setattr("backend.agents.test_design.llm_enabled", lambda: False)
    cart = "https://shop.example/index.php?rt=checkout/cart"
    pay = "https://shop.example/index.php?rt=checkout/checkout"
    state = {
        "url": "https://shop.example/",
        "run_dir": str(tmp_path),
        "site_key": "shop",
        "log": [],
        "app_map": [
            {"url": cart, "slug": "cart", "title": "Cart", "status": 200, "auth": False, "page_type": "cart",
             "links": [], "buttons": [{"text": "Update", "selector": "#up"}], "inputs": [], "forms": []},
            {"url": pay, "slug": "pay", "title": "Checkout", "status": 200, "auth": False,
             "links": [], "inputs": [], "forms": [],
             "buttons": [{"text": "Place order", "selector": "#order", "role": "button"}]},
            {"url": "https://shop.example/index.php?rt=product/category", "slug": "shop", "title": "Shop",
             "status": 200, "auth": False, "links": [], "buttons": [], "inputs": [], "forms": []},
        ],
    }
    cases = test_design_agent(state)["test_cases"]
    assert not any(c.get("url") == pay and not c.get("blocked") for c in cases)
    assert any(c.get("blocked") and "Place order" in c.get("title", "") for c in cases)
    assert any(c.get("url") == cart and not c.get("blocked") for c in cases)


def test_the_every_page_check_does_not_open_checkout_again():
    from backend.agents.script_generator import site_script
    from backend.agents.test_design import small_checks
    cart = {"url": "https://shop.example/index.php?rt=checkout/cart", "slug": "cart", "auth": False,
            "title": "Cart", "imageCount": 1, "links": []}
    checkout = {"url": "https://shop.example/index.php?rt=checkout/checkout", "slug": "pay", "auth": False,
                "title": "Checkout", "imageCount": 2, "links": [
                    {"href": "https://shop.example/index.php?rt=checkout/confirm", "text": "Continue"},
                    {"href": "https://shop.example/index.php?rt=product/category", "text": "Shop"},
                ]}
    shop = {"url": "https://shop.example/index.php?rt=product/category", "slug": "shop", "auth": False,
            "title": "Shop", "links": []}
    code = site_script([cart, checkout, shop])
    assert "checkout/cart" in code and "product/category" in code
    assert "checkout/checkout" not in code
    opened = next(c for c in small_checks([cart, checkout, shop], []) if c["id"] == "site_pages_open")
    assert "2 pages" in opened["title"] and "1 checkout or payment page" in opened["title"]
    links = next(c for c in small_checks([cart, checkout, shop], []) if c["id"] == "site_links")
    assert "1 links" in links["title"]


def test_checkout_addresses_are_not_opened_by_the_link_checks():
    from backend.agents.script_generator import all_links_script
    pages = [{
        "url": "https://shop.example/cart", "slug": "cart", "title": "Cart",
        "links": [
            {"href": "https://shop.example/checkout", "text": "Continue"},
            {"href": "https://shop.example/index.php?rt=checkout/checkout", "text": "Continue"},
            {"href": "https://shop.example/index.php?rt=checkout/cart", "text": "Cart"},
            {"href": "https://shop.example/product/1", "text": "Saree"},
        ],
    }]
    code, count = all_links_script(pages)
    assert count == 2
    listed = code.split("LINKS = ", 1)[1].split("SECTIONS", 1)[0]
    assert "shop.example/checkout" not in listed
    assert "checkout/checkout" not in listed
    assert "checkout/cart" in code and "product/1" in code


def test_a_role_check_does_not_open_checkout_again(tmp_path, monkeypatch):
    from backend.agents.discovery import _explore_roles
    from backend.config import settings
    from backend.roles import role_cases, roles_script

    opened = []

    class Loc:
        def inner_text(self, timeout=5000):
            return "Account"

        def count(self):
            return 0

    class Tab:
        def __init__(self):
            self.url = "https://shop.example/account"

        def goto(self, url, **kwargs):
            opened.append(url)
            self.url = url
            return type("Resp", (), {"status": 200})()

        def wait_for_load_state(self, *args, **kwargs):
            return None

        def locator(self, selector):
            return Loc()

    class Ctx:
        def storage_state(self, path):
            from pathlib import Path
            Path(path).write_text("{}", encoding="utf-8")

        def close(self):
            return None

    monkeypatch.setattr(
        "backend.agents.discovery.log_in",
        lambda *args, **kwargs: (Tab(), {"logged_in": True, "outcome": "ok"}),
    )
    monkeypatch.setattr("backend.agents.discovery.looks_logged_out", lambda *args, **kwargs: False)
    monkeypatch.setattr(settings, "test_accounts", [
        {"role": "admin", "username": "admin@x.test", "password": "x"},
        {"role": "viewer", "username": "viewer@x.test", "password": "x"},
    ])
    home = "https://shop.example/account"
    cart = "https://shop.example/index.php?rt=checkout/cart"
    pay = "https://shop.example/index.php?rt=checkout/checkout"
    app = [
        {"url": home, "auth": True, "final_url": home},
        {"url": pay, "auth": True, "final_url": pay},
        {"url": cart, "auth": True},
    ]
    session = {"user": "admin@x.test", "form": {"user": "#email"}, "login_page": "https://shop.example/login"}
    roles = _explore_roles(lambda: Ctx(), session, app, tmp_path)
    assert pay not in opened
    assert home in opened and cart in opened
    viewer = roles["roles"]["viewer"]["pages"]
    assert viewer[pay]["access"] == "blocked"
    assert viewer[cart]["access"] == "ok"
    cases = role_cases({"roles": roles})
    assert all(c["url"] != pay for c in cases)
    assert any(c["url"] == cart for c in cases)
    code = roles_script(
        [
            {"id": "role_1", "url": cart, "title": "Role viewer can open cart",
             "spec": {"role": "viewer", "url": cart, "expect": "open"}},
            {"id": "role_9", "url": pay, "title": "Role viewer can open checkout",
             "spec": {"role": "viewer", "url": pay, "expect": "open"}},
        ],
        ["import re"],
    )
    assert "def test_role_1" in code
    assert "def test_role_9" not in code
    assert pay not in code


def test_a_generated_open_does_not_start_checkout():
    import ast
    import re
    from pathlib import Path

    import pytest
    src = Path("backend/templates/conftest.py").read_text(encoding="utf-8")
    code = "\n\n".join(
        ast.get_source_segment(src, node)
        for node in ast.parse(src).body
        if getattr(node, "name", None) in {"_payment_target", "_patched_goto"}
    )
    ns = {"re": re, "pytest": pytest, "NAV_TIMEOUT_MS": 30000,
          "_pw": type("Pw", (), {"Error": type("Error", (Exception,), {})})()}
    exec(code, ns)
    opened = []

    def real(self, url, **kwargs):
        opened.append(url)
        raise RuntimeError("opened")

    goto = ns["_patched_goto"](real)
    pay = "https://shop.example/index.php?rt=checkout/checkout"
    cart = "https://shop.example/index.php?rt=checkout/cart"
    with pytest.raises(pytest.skip.Exception):
        goto(object(), pay)
    assert opened == []
    with pytest.raises(RuntimeError, match="opened"):
        goto(object(), cart, wait_until="commit")
    assert opened == [cart]


def test_a_generated_read_does_not_fetch_checkout():
    import ast
    import re
    from pathlib import Path
    from urllib.parse import urljoin

    import pytest
    src = Path("backend/templates/conftest.py").read_text(encoding="utf-8")
    code = "\n\n".join(
        ast.get_source_segment(src, node)
        for node in ast.parse(src).body
        if getattr(node, "name", None) in {"_payment_target", "_checked"}
    )
    ns = {"re": re, "pytest": pytest, "urljoin": urljoin, "_blocked": lambda url, navigation=False: None}
    exec(code, ns)
    opened = []

    class Resp:
        def __init__(self, status, location=""):
            self.status = status
            self.headers = {"location": location} if location else {}

    def real(self, url, **kwargs):
        opened.append(url)
        if url.endswith("checkout/cart"):
            return Resp(302, "https://shop.example/index.php?rt=checkout/confirm")
        return Resp(200)

    read = ns["_checked"](real)
    pay = "https://shop.example/index.php?rt=checkout/checkout"
    cart = "https://shop.example/index.php?rt=checkout/cart"
    product = "https://shop.example/product/1"
    with pytest.raises(pytest.skip.Exception):
        read(object(), pay)
    assert opened == []
    resp = read(object(), cart)
    assert resp.status == 302
    assert opened == [cart]
    opened.clear()
    assert read(object(), product).status == 200
    assert opened == [product]


def test_a_submit_button_formaction_to_checkout_is_not_filled():
    import ast
    import time
    from pathlib import Path

    from playwright.sync_api import sync_playwright

    from backend.forms import data_forms
    from backend.observe import Explorer
    from backend.swarm import stored_control_opens_payment
    page_url = "https://shop.example/contact"
    submit = {"text": "Continue", "selector": "#go", "formaction": "index.php?rt=checkout/confirm"}
    form = {
        "selector": "#note",
        "method": "post",
        "action": "/contact",
        "submit": submit,
        "fields": [{"selector": "#name", "type": "text", "label": "Name", "name": "name", "required": True}],
    }
    assert stored_control_opens_payment(page_url, submit)
    assert stored_control_opens_payment(page_url, {"formaction": "index.php?rt=checkout/cart"}) is False
    assert data_forms([{
        "url": page_url, "slug": "contact", "title": "Contact", "page_type": "content",
        "inputs": form["fields"], "forms": [form],
    }]) == []
    entry = {"forms": [form]}
    Explorer("", lambda *_a, **_k: None, time.time() + 30).fill_forms(type("P", (), {"url": page_url})(), page_url, entry)
    assert entry["form_fills"][0]["sent"] is False
    assert "never filled" in entry["form_fills"][0]["not_sent"]
    src = Path("backend/templates/conftest.py").read_text(encoding="utf-8")
    js = next(
        ast.literal_eval(node.value)
        for node in ast.parse(src).body
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CONTROL_TEXT_JS"
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            tab = browser.new_page()
            tab.set_content(
                '<form action="/contact">'
                '<button id="go" formaction="index.php?rt=checkout/confirm">Continue</button>'
                "</form>"
            )
            names = tab.locator("#go").evaluate(js, False)
        finally:
            browser.close()
    assert names[8] == "index.php?rt=checkout/confirm"


def test_a_form_that_posts_to_checkout_is_not_filled():
    from backend.form_rules import pair_cases
    from backend.forms import data_forms, form_cases
    stay = {
        "selector": "#in", "type": "date", "label": "Start date", "name": "start", "required": True,
    }
    leave = {
        "selector": "#out", "type": "date", "label": "End date", "name": "end", "required": True,
    }
    note = {
        "selector": "#note", "type": "text", "label": "Note", "name": "note", "required": True,
    }
    page = {
        "url": "https://shop.example/guest",
        "slug": "guest",
        "title": "Guest",
        "auth": False,
        "page_type": "content",
        "inputs": [stay, leave, note],
        "forms": [
            {
                "selector": "#pay",
                "method": "post",
                "action": "index.php?rt=checkout/confirm",
                "submit": {"text": "Continue", "selector": "#go"},
                "fields": [stay, leave],
            },
            {
                "selector": "#msg",
                "method": "post",
                "action": "/contact",
                "submit": {"text": "Send", "selector": "#send"},
                "fields": [note],
            },
        ],
    }
    forms = data_forms([page])
    assert [f["form"]["selector"] for f in forms] == ["#msg"]
    titles = [c["title"] for c in form_cases([page])]
    assert any("Send" in t for t in titles)
    assert not any("Continue" in t for t in titles)
    book = {
        "url": "https://shop.example/book",
        "slug": "book",
        "title": "Book",
        "auth": False,
        "page_type": "content",
        "inputs": [stay, leave],
        "forms": [{
            "selector": "#stay",
            "method": "post",
            "action": "/book",
            "submit": {"text": "Continue", "selector": "#book"},
            "fields": [stay, leave],
        }],
    }
    pairs = pair_cases([page, book])
    assert any(c.get("url") == book["url"] for c in pairs)
    assert not any(c.get("url") == page["url"] for c in pairs)


def test_extra_pages_of_one_kind_do_not_include_checkout():
    from backend.items import item_cases
    pay = "https://shop.example/index.php?rt=checkout/confirm"
    order = "https://shop.example/order/9"
    cart = "https://shop.example/index.php?rt=checkout/cart"
    cases = item_cases([], {"item_types": {
        "/order/{id}": {"smoke": [pay, order, cart]},
        "/checkout/{id}": {"smoke": [pay]},
    }})
    urls = [u for c in cases for u in c["spec"]["urls"]]
    assert urls == [order, cart]
    assert pay not in urls
