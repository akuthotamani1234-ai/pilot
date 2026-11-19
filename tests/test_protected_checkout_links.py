"""Pay/checkout destinations are recorded as protected, even when the label says Continue."""
from backend.agents.test_design import blocked_cases, coverage, learned_cases, rule_based_cases, safe_buttons
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


def test_checkout_addresses_are_not_opened_by_the_link_checks():
    from backend.agents.script_generator import all_links_script
    pages = [{
        "url": "https://shop.example/cart", "slug": "cart", "title": "Cart",
        "links": [
            {"href": "https://shop.example/checkout", "text": "Continue"},
            {"href": "https://shop.example/index.php?rt=checkout/cart", "text": "Cart"},
            {"href": "https://shop.example/product/1", "text": "Saree"},
        ],
    }]
    code, count = all_links_script(pages)
    assert count == 2
    assert "shop.example/checkout" not in code.split("LINKS = ", 1)[1].split("SECTIONS", 1)[0]
    assert "checkout/cart" in code and "product/1" in code
