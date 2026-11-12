"""The cart and the search of automationexercise.com (Nov 2, 2026, the run the user watched): the user asked that
the cart - except checkout - is tested completely (add, more of it, remove, the price following the quantity) and
that search works. What stopped it, all the tool's own mistakes:
  * every card's link says 'View Product': that was taken as each item's name - the search looked for 'Product'
    (and the journey for an item named 'View');
  * the product page has no <h1>: the sidebar's 'Category' <h2> was taken as the product's name, so the quantity
    test looked for a 'CATEGORY' line in the cart (4 item tests failed the same way);
  * the Test Cases page ('Test Case 22: Add to cart from Recommended items') was taken as THE product page - no list
    opens it, so the whole shopping journey (more of it -> the total, remove) was never made;
  * the cart has no grand total ('Price | Quantity | Total' per line): the heading row's next line - the first
    item's unit price - was read as the cart's total;
  * the cart's remove control is only a cross icon (<a class="cart_quantity_delete"><i class="fa fa-times">): never
    found, and its code name ('delete') made it 'protected' - removing from your own cart was never tested.
The pages in automationexercise_pages.json are that run's own pages (trimmed)."""
import json
from pathlib import Path

import pytest

PRODUCTS = """<!doctype html><html><body><div class="features_items"><h2 class="title text-center">All Products</h2>
""" + "".join(f"""<div class="col-sm-4"><div class="product-image-wrapper"><div class="single-products">
  <div class="productinfo text-center"><img src="/p{n}.jpg" alt="ecommerce website products"><h2>Rs. {price}</h2>
  <p>{name}</p><a href="#" data-product-id="{n}" class="btn btn-default add-to-cart">Add to cart</a></div></div>
  <div class="choose"><ul class="nav nav-pills nav-justified"><li><a href="/product_details/{n}">View Product</a></li>
  </ul></div></div></div>""" for n, name, price in ((1, "Blue Top", 500), (2, "Men Tshirt", 400),
                                                   (3, "Sleeveless Dress", 1000))) + "</div></body></html>"

PRODUCT = """<!doctype html><html><body><div class="left-sidebar"><h2>Category</h2><div class="panel">Women</div></div>
<div class="product-details"><div class="product-information"><h2>Blue Top</h2><p>Category: Women &gt; Tops</p>
<span><span>Rs. 500</span><label>Quantity:</label><input type="number" id="quantity" value="1"></span></div></div>
</body></html>"""

CART = """<!doctype html><html><head><style>.fa-times::before {{ content: "x"; }}</style></head><body>
<table class="table table-condensed" id="cart_info_table">
<thead><tr class="cart_menu"><td class="image">Item</td><td class="description">Description</td><td class="price">Price</td>
<td class="quantity">Quantity</td><td class="total">Total</td><td></td></tr></thead><tbody>
<tr id="product-1"><td class="cart_product"><img src="/p1.jpg"></td><td class="cart_description"><h4>
<a href="/product_details/1">Blue Top</a></h4><p>Women &gt; Tops</p></td><td class="cart_price"><p>Rs. {price}</p></td>
<td class="cart_quantity"><button class="disabled">{qty}</button></td><td class="cart_total"><p class="cart_total_price">
Rs. {total}</p></td><td class="cart_delete"><a class="cart_quantity_delete" data-product-id="1"><i class="fa fa-times">
</i></a></td></tr></tbody></table>
<script>document.querySelectorAll('.cart_quantity_delete').forEach(a => a.onclick = () => {{
  setTimeout(() => {{ a.closest('tr').style.display = 'none'; }}, 300); }});</script></body></html>"""


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b.new_page()
        b.close()


@pytest.fixture(scope="module")
def helpers():
    """The generated tests' own helpers (journeys + results + cart), as a generated test file has them."""
    from backend.agents.script_generator import CART_HELPERS, JOURNEY_HELPERS, RESULT_HELPERS
    ns = {}
    exec("import re\nimport pytest\nfrom playwright.sync_api import expect\n" + JOURNEY_HELPERS + RESULT_HELPERS
         + CART_HELPERS, ns)
    return ns


def test_each_card_is_named_by_its_item_not_by_its_view_product_link(page):
    from backend.agents.discovery import ITEMS_JS
    page.set_content(PRODUCTS)
    got = page.evaluate(ITEMS_JS, {"mark": True, "hints": []})
    assert got["names"] == ["Blue Top", "Men Tshirt", "Sleeveless Dress"], got["names"]  # (was: 'View Product' x 3)


def test_the_search_word_is_a_word_of_a_real_item():
    from backend.agents.test_design import _item_names, site_search_word
    pages = json.loads(Path("tests/automationexercise_pages.json").read_text(encoding="utf-8"))
    products = next(p for p in pages if p["slug"] == "products")
    names = _item_names(products)
    assert "Blue Top" in names and "View Product" not in names, names[:6]
    word = site_search_word(pages)
    assert word.lower() not in ("product", "products", "view") and any(word.lower() in n.lower() for n in names), word


def test_the_product_name_is_the_product_information_heading_not_the_sidebar(page, helpers):
    page.set_content(PRODUCT)
    assert helpers["_heading_name"](page) == "Blue Top"  # (was: 'Category' - the sidebar's <h2>)


def test_the_shopping_journey_is_made_from_a_product_page_a_list_opens():
    from backend.agents.test_design import builtin_journeys
    pages = json.loads(Path("tests/automationexercise_pages.json").read_text(encoding="utf-8"))
    for p in pages:
        p["site_word"] = "Dress"  # (the test design sets the site's search word on every page)
    journey = next((j for j in builtin_journeys(pages, limit=40) if j["journey"] == "product"), None)
    assert journey is not None  # (was: none - the Test Cases page was taken as the product page)
    s = journey["spec"]
    assert s["url"].endswith("/products") and s["cart_url"].endswith("/view_cart") and s["change_cart"]
    assert s["word"] == "Dress" and "Remove the line this test added" in " ".join(journey["steps"])
    assert "checkout" in journey["steps"][-1].lower()  # (stops before it)


def test_removing_from_your_own_cart_is_allowed_checkout_never():
    from backend.actions import action_risk
    assert action_risk("", "a.cart_quantity_delete") == "test_account"  # (was: protected - 'delete')
    assert action_risk("Remove from cart", "button.remove") == "test_account"
    assert action_risk("Proceed To Checkout", "a.check_out") == "protected"
    assert action_risk("Delete Account", "a[href='/delete_account']") == "protected"


def test_the_cart_without_a_grand_total_follows_the_quantity_by_its_lines(page, helpers):
    h = helpers
    page.set_content(CART.format(price=500, qty=1, total=500))
    row = h["_cart_row"](page, "Blue Top")
    assert h["_cart_total"](page) is None  # (was: 500 - the first item's unit price under 'Total')
    assert (h["_line_qty"](row), h["_line_price"](row), h["_line_total"](row)) == (1.0, 500.0, 500.0)
    one = h["_totals"](page, "Blue Top")
    page.set_content(CART.format(price=500, qty=2, total=1000))  # one more Blue Top
    assert "1000" in h["_total_follows"](one, h["_totals"](page, "Blue Top"), 500.0, "One more 'Blue Top'")
    page.set_content(CART.format(price=500, qty=2, total=500))  # a cart that forgot the quantity
    with pytest.raises(AssertionError, match="should add 500 to the line's total, it went 500 -> 500"):
        h["_total_follows"](one, h["_totals"](page, "Blue Top"), 500.0, "One more 'Blue Top'")


def test_the_cross_icon_removes_the_line_and_it_must_be_gone(page, helpers):
    page.set_content(CART.format(price=500, qty=1, total=500))
    helpers["_remove_own"](page, "Blue Top")  # (was: no remove control found - nothing tested)
    assert helpers["_shown_rows"](page, "Blue Top") == 0
    page.set_content(CART.format(price=500, qty=1, total=500).replace("a.closest('tr').style.display = 'none';", ""))
    with pytest.raises(AssertionError, match="did not take 'Blue Top' out of the cart"):
        helpers["_remove_own"](page, "Blue Top")  # (a cart whose remove does nothing: that is caught)
