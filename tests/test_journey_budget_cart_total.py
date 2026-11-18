"""Phase 1 lesson: many short Shop-on journeys must not crowd out the cart-total shopping journey."""
from backend.agents.test_design import LARGE, builtin_journeys


def _product(n: int) -> dict:
    return {
        "url": f"http://shop.test/product/{n}",
        "slug": f"product_{n}",
        "page_type": "product",
        "auth": True,
        "title": f"Item {n}",
        "headings": [f"Item {n}"],
        "buttons": [{"text": "Add to cart", "selector": "#add-to-cart", "count": 1}],
        "links": [{"href": "http://shop.test/cart", "text": "Cart"}],
        "inputs": [{"tag": "select", "name": "size", "id": "size", "label": "Size", "selector": "#size",
                    "options": [{"value": "S", "text": "S"}, {"value": "M", "text": "M"}]}],
        "forms": [],
        "itemLinks": {"links": [], "selector": ""},
    }


def test_product_change_cart_journey_survives_many_product_pages():
    shop = {
        "url": "http://shop.test/shop",
        "slug": "shop",
        "page_type": "listing",
        "auth": True,
        "title": "Shop",
        "headings": ["Shop"],
        "buttons": [],
        "links": [{"href": "http://shop.test/cart", "text": "Cart"}],
        "inputs": [{"tag": "input", "type": "search", "name": "q", "id": "q", "label": "Search",
                    "selector": "#q"}],
        "forms": [],
        "itemLinks": {
            "selector": ".card a",
            "links": [{"href": f"http://shop.test/product/{n}", "text": f"Item {n}"} for n in range(1, 25)],
        },
        "site_word": "Item",
    }
    cart = {
        "url": "http://shop.test/cart",
        "slug": "cart",
        "page_type": "cart",
        "auth": True,
        "title": "Cart",
        "headings": ["Your cart"],
        "buttons": [],
        "links": [],
        "inputs": [],
        "forms": [],
        "itemLinks": {"links": [], "selector": ""},
    }
    pages = [shop, cart] + [_product(n) for n in range(1, 25)]
    for p in pages:
        p["site_word"] = "Item"
    journeys = builtin_journeys(pages, limit=LARGE)
    product = next(j for j in journeys if j["journey"] == "product")
    assert product["spec"]["change_cart"] is True
    assert any(j["journey"] == "product" for j in journeys[:3]), journeys[:5]
    # Under the default LARGE budget the cart-total journey must still be present.
    assert "cart total goes up by exactly its price" in " ".join(product["steps"])
