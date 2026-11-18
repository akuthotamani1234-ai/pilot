"""Phase 1/2 lesson: many short Shop-on journeys must not crowd out priority journeys."""
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


def _pages_with_orders():
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
    orders = {
        "url": "http://shop.test/orders",
        "slug": "orders",
        "page_type": "orders",
        "auth": True,
        "title": "Orders",
        "headings": ["Orders"],
        "buttons": [],
        "links": [{"href": "http://shop.test/orders/1001", "text": "Order 1001"}],
        "inputs": [],
        "forms": [],
        "itemLinks": {"links": [], "selector": ""},
        "features": [],
    }
    detail = {
        "url": "http://shop.test/orders/1001",
        "slug": "order_1001",
        "page_type": "order_detail",
        "auth": True,
        "title": "Order 1001",
        "headings": ["Order 1001"],
        "buttons": [],
        "links": [{"href": "http://shop.test/orders/1001/tracking", "text": "Track shipment"}],
        "inputs": [],
        "forms": [],
        "itemLinks": {"links": [], "selector": ""},
    }
    pages = [shop, cart, orders, detail] + [_product(n) for n in range(1, 25)]
    for p in pages:
        p["site_word"] = "Item"
    return pages, orders, detail


def test_product_change_cart_journey_survives_many_product_pages():
    pages, _, _ = _pages_with_orders()
    journeys = builtin_journeys(pages, limit=LARGE)
    product = next(j for j in journeys if j["journey"] == "product")
    assert product["spec"]["change_cart"] is True
    assert any(j["journey"] == "product" for j in journeys[:3]), journeys[:5]
    assert "cart total goes up by exactly its price" in " ".join(product["steps"])


def test_orders_tracking_journey_survives_many_product_pages():
    pages, _, _ = _pages_with_orders()
    journeys = builtin_journeys(pages, limit=LARGE)
    kinds = [j["journey"] for j in journeys]
    assert "orders" in kinds, kinds
    assert kinds.index("orders") < kinds.index("shop")
    order = next(j for j in journeys if j["journey"] == "orders")
    assert any("Track" in step or "tracking" in step.lower() for step in order["steps"] + [order["title"]])
