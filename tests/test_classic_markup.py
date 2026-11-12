"""Older template shops (tests/classic_shop.py, a real hidden browser) - the page structures behind the false results
of the AutomationTestStore run (runs/automationteststore.com_20261027_235636):
  * the item list is the PRODUCT CARDS - not the header menu, the breadcrumb, the product tabs, or every link of a
    <body class="product-category"> (search + sort read 'Login or register', 'Specials', 'Account' ...);
  * a menu's address does not contain the cart's count and total ('1 ITEMS - $29.50' did not exist in a fresh browser);
  * tab links ('#review' while <base href> points to the home page) are tabs, not broken '#section' links;
  * 'Print' and 'Back to top' have an effect that can be observed (was: 'gave no visible response' / 'changed nothing');
  * pages picked by ?rt=<route> are different pages (was: the cart, contact and site map were skipped as 'the same
    address pattern', and the registry had 2 page patterns for 29 pages)."""
import pytest

from tests.classic_shop import CATEGORIES, PRODUCTS, ClassicShop


@pytest.fixture(scope="module")
def shop():
    s = ClassicShop().start()
    yield s
    s.stop()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    from backend.observe import DIALOG_INIT_JS
    ctx = browser.new_context(viewport={"width": 1366, "height": 900})
    ctx.add_init_script(DIALOG_INIT_JS)
    yield ctx.new_page()
    ctx.close()


def _read(page, url):
    from backend.agents.discovery import EXTRACT_JS
    page.goto(url)
    return page.evaluate(EXTRACT_JS)


def _names(cat, sub=None):
    return [p["name"] for p in PRODUCTS if p["cat"] == cat and (sub is None or p["sub"] == sub)]


def test_the_item_list_is_the_product_cards_not_the_menus(shop, page):
    data = _read(page, f"{shop.url}/index.php?rt=product/category&path=10")
    items = data["itemLinks"]
    assert [l["text"] for l in items["links"]] == _names(10)[:8]  # the 8 cards of the first page, in order
    assert not items["selector"].startswith("body"), items["selector"]
    assert page.locator(items["selector"]).count() == 8  # one link per card: the cards can be counted
    for word in ("Login or register", "Specials", "Account", "Home", "Makeup"):
        assert word not in [l["text"] for l in items["links"]]
    # the tests read the result list the same way, on whatever page they are (search results ...)
    from backend.agents.discovery import ITEMS_JS
    page.goto(f"{shop.url}/index.php?rt=product/search&keyword=lip")
    found = page.evaluate(ITEMS_JS, True)
    assert sorted(found["names"]) == sorted(p["name"] for p in PRODUCTS if "lip" in p["name"].lower())
    assert all("$" in c for c in found["cards"])  # (each card's text, with its price)
    assert page.locator('[data-qa-item="0"]').count() == 1  # marked: a test can click the card it read


def test_a_search_with_two_results_is_read_with_the_lists_address_from_exploring(shop, page):
    """2 cards are too few to tell a list from a menu on their own - with the address of the website's item list
    (found while exploring) they are read: the search test checks the real results, not 'no list'."""
    from backend.agents.discovery import EXTRACT_JS, ITEMS_JS
    page.goto(f"{shop.url}/index.php?rt=product/category&path=10")
    hint = page.evaluate(EXTRACT_JS)["itemLinks"]["selector"]
    page.goto(f"{shop.url}/index.php?rt=product/search&keyword=velvet")
    assert page.evaluate(ITEMS_JS, True) == {}
    found = page.evaluate(ITEMS_JS, {"mark": True, "hints": [hint]})
    assert found["names"] == ["Velvet Matte Lipstick", "Velvet Lip Balm"], found
    assert all("$" in c and "Login" not in c for c in found["cards"])  # (each card: its own text, not the page)
    assert page.locator('[data-qa-item="1"]').inner_text() == "Velvet Lip Balm"


def test_confirm_order_is_never_a_confirm_box_and_a_cart_line_box_gets_no_test_of_its_own():
    from backend.agents.test_design import control_cases, data_cases
    checkout = {"url": "https://s.test/index.php?rt=checkout/checkout", "title": "Checkout", "inputs": [],
                "buttons": [{"text": "Confirm Order", "selector": "#confirm", "kind": "dialog"},  # (an older map)
                            {"text": "JS Confirm", "selector": "#js", "kind": "dialog"}]}
    titles = [c["title"] for c in control_cases(checkout)]
    assert any("JS Confirm" in t for t in titles) and not any("Confirm Order" in t for t in titles), titles
    line = {"tag": "input", "type": "text", "name": "quantity[1:]", "selector": 'input[name="quantity[1:]"]',
            "label": "Quantity"}
    cart = {"url": "https://s.test/index.php?rt=checkout/cart", "title": "Cart", "page_type": "cart", "buttons": [],
            "inputs": [line]}
    assert not data_cases(cart) and not control_cases(cart)  # (only there while the cart holds that item)
    option = {"tag": "select", "type": "select-one", "name": "option[350]", "selector": "#option350", "label": "Colour",
              "options": [{"value": "1", "text": "Red"}, {"value": "2", "text": "Blue"}]}
    product = dict(cart, page_type="product", inputs=[option])
    assert [c["kind"] for c in control_cases(product)] == ["dropdown"]  # a product's own option IS tested


def test_each_dropdown_is_named_by_the_words_written_before_it(shop, page):
    """'Sort By: <select> Per page: <select>' - the second box is 'Per page' (it was named 'Sort By' too)."""
    data = _read(page, f"{shop.url}/index.php?rt=product/category&path=10")
    labels = {i["selector"]: i["label"].rstrip(": ") for i in data["inputs"] if i["tag"] == "select"}
    assert labels.get("#sort") == "Sort By" and labels.get("#limit") == "Per page", labels


def test_a_product_page_has_no_item_list_of_breadcrumbs_and_tabs(shop, page):
    from backend.features import page_features, page_type
    data = _read(page, f"{shop.url}/index.php?rt=product/product&product_id=1")
    entry = dict(data, url=f"{shop.url}/index.php?rt=product/product&product_id=1", title="Velvet Matte Lipstick")
    assert not (data["itemLinks"] or {}).get("links"), data["itemLinks"]
    kinds = {f["kind"] for f in page_features(entry)}
    assert "items" not in kinds and "add_to_cart" in kinds
    assert page_type(entry) == "product"


def test_menu_addresses_do_not_contain_the_cart_count(shop, page):
    data = _read(page, f"{shop.url}/index.php?rt=product/category&path=20")
    cart = next(h for h in data["hovers"] if "ITEMS" in (h.get("text") or ""))
    assert not any(ch.isdigit() or ch in "$€" for ch in cart["selector"]), cart["selector"]
    assert page.locator(cart["selector"]).count() == 1
    page.locator("a.productcart[data-id]").first.click()  # the cart changes: '1 ITEMS - $59.00' ...
    page.wait_for_function("() => !document.querySelector('.cart_total_text').innerText.startsWith('0 ')")
    assert page.locator(cart["selector"]).count() == 1  # ... the same address still finds the menu


def test_tab_links_are_tabs_not_broken_section_links(shop, page):
    from backend.agents.discovery import _sections
    url = f"{shop.url}/index.php?rt=product/product&product_id=1"
    data = _read(page, url)
    review = next(l for l in data["links"] if l.get("text", "").startswith("Reviews"))
    assert review["toggle"]  # (data-toggle="tab": its script shows the tab, the <base href> is never followed)
    assert not [s for s in _sections(data["links"], url, "127.0.0.1") if s["section"] in ("review", "producttag")]
    tabs = [b for b in data["buttons"] if b.get("kind") == "tab"]
    assert {"Description", "Reviews (0)"} <= {b["text"] for b in tabs}  # (tested as tabs instead)


def test_print_and_back_to_top_have_an_observable_effect(shop, page):
    from backend.observe import SNAPSHOT_JS, diff
    page.goto(f"{shop.url}/index.php?rt=product/product&product_id=1")
    before = page.evaluate(SNAPSHOT_JS, None)
    page.locator("a.productprint").click()  # window.print(): written down, the print dialog never opens
    page.wait_for_function("() => (window.__qaDialogs || []).length > 0", timeout=5000)  # (a javascript: link runs
    ev = diff(before, page.evaluate(SNAPSHOT_JS, None))                                 # just after the click)
    assert ev["effect"] == "message" and ev["message"].startswith("print"), ev
    page.goto(shop.url)
    page.locator("#gotop").scroll_into_view_if_needed()
    before = page.evaluate(SNAPSHOT_JS, None)
    page.locator("#gotop").click()
    page.wait_for_timeout(300)
    ev = diff(before, page.evaluate(SNAPSHOT_JS, None))
    assert ev["effect"] == "scroll", ev  # (was: 'changed nothing')


def test_the_grid_button_that_is_already_on_and_nameless_controls_are_not_required_to_respond():
    from backend.agents.test_design import _must_respond
    grid = {"tag": "button", "type": "button", "text": "", "accname": "", "named": False,
            "html": '<button class="btn btn-orange" id="grid" type="button">'}
    assert not _must_respond(grid, "btn btn orange")  # a name made of CSS classes: what it should do is unknown
    assert _must_respond({"tag": "button", "type": "button", "text": "Notify me", "named": True,
                          "html": '<button id="notify" type="button">'}, "Notify me")


def test_pages_picked_by_the_route_are_different_pages():
    from backend.agents.discovery import _pattern
    from backend.registry import page_pattern
    base = "https://shop.test/index.php?rt="
    assert _pattern(base + "checkout/cart", False) != _pattern(base + "account/login", False)
    assert _pattern(base + "product/product&product_id=5", False) == _pattern(base + "product/product&product_id=7",
                                                                              False)
    # the navigation context (path=68, keyword=...) is not another page
    assert _pattern(base + "product/product&path=68&product_id=5", False) == \
        _pattern(base + "product/product&product_id=7", False)
    assert _pattern(base + "product/category&path=68", False) == _pattern(base + "product/category&path=68_70", False)
    assert "{id}" in _pattern(base + "product/product&product_id=5", False)[1]  # (an item page: its id is in it)
    assert _pattern("https://shop.test/product/12", False) == _pattern("https://shop.test/product/13", False)
    assert _pattern("https://shop.test/about", False) is None
    pats = {page_pattern({"url": base + r}) for r in ("checkout/cart", "account/login", "content/contact",
                                                       "product/product&product_id=1", "product/product&product_id=2")}
    assert len(pats) == 4
    assert page_pattern({"url": "https://shop.test/shop?category=fruit"}) == page_pattern({"url": "https://shop.test/shop"})
    # where to go AFTER a page is not the page: /signin?next=/dashboard is the sign-in page
    from backend.agents.discovery import _auth_link
    assert _auth_link("https://shop.test/signin?next=/dashboard") and _auth_link(base + "account/login")
    assert not _auth_link(base + "account/account") and _pattern("https://shop.test/signin?next=/x", False)[1] == "/signin"


def test_the_search_word_is_a_real_product_name_of_the_site():
    from backend.agents.test_design import site_search_word
    pages = [{"itemLinks": {"links": [{"text": p["name"]} for p in PRODUCTS if p["cat"] == c]}} for c in CATEGORIES]
    pages.append({"itemLinks": {}, "itemNames": ["Welcome to ClassicShop!", "Home"]})  # (no headings, no menu words)
    word = site_search_word(pages)
    hits = [p["name"] for p in PRODUCTS if word.lower() in p["name"].lower()]
    assert word and 2 <= len(hits) <= 4, (word, hits)  # finds a few items, not all and not none
