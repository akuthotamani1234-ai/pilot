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
