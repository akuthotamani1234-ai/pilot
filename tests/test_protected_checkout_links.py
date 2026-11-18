"""Pay/checkout <a class="btn"> links must be recorded as protected (Gate J classic)."""
from backend.agents.test_design import blocked_cases
from backend.features import page_features


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
