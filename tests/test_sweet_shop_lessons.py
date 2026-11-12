"""What the run on sweetshop.netlify.app (runs/sweetshop.netlify.app_20261102_010622) got wrong - each one fixed and
kept fixed here (the pages below are built like the ones there):
  * its 16 'Add to Basket' buttons are <a> WITHOUT an address (the page's script handles them): the crawler never saw
    them, so the shop got no add-to-basket / basket test at all - and then still no shopping journey: its basket is a
    normal link (<a href="/basket">0 Basket</a>), the journey only looked for a basket BUTTON;
  * at phone width a delivery choice was 'covered by <label>': its own label (a styled radio button);
  * 'Empty Basket' asked 'Are you sure ...?' while exploring (the basket held a sweet), not in its test (an empty
    basket - the site asks only when there is something to empty): "showed no message".
(Checked by hand, real: the 'About' link of the basket page goes to /bout (404); the picture img/whan.jpg is missing.)"""
import pytest


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def test_add_to_basket_links_without_an_address_are_controls(browser):
    from backend.agents.discovery import EXTRACT_JS
    from backend.agents.test_design import features
    page = browser.new_page()
    try:
        cards = "".join(f'<div class="card"><h4>{n}</h4><p>£{p}</p><a class="btn btn-success addItem" data-id="{i}" '
                        f'data-name="{n}" data-price="{p}">Add to Basket</a></div>'
                        for i, (n, p) in enumerate((("Chocolate Cups", "1.00"), ("Sherbert Straws", "0.75"),
                                                    ("Sherbert Discs", "0.95")), start=1))
        page.set_content(f'<!doctype html><html><head><title>Sweets</title></head><body><a name="top"></a>'
                         f'<h1>Browse sweets</h1>{cards}<a href="/basket">Basket</a></body></html>')
        data = page.evaluate(EXTRACT_JS)
        add = [b for b in data["buttons"] if b["text"] == "Add to Basket"]
        assert add and add[0]["count"] == 3, data["buttons"]  # (was: not seen at all)
        assert not [b for b in data["buttons"] if b["tag"] == "a" and not b["text"].strip()]  # (the bookmark: no control)
        p = dict(data, url="https://sweets.test/sweets", slug="sweets", title="Sweets", auth=False, status=200,
                 page_type="listing")
        assert features(p)["add"] == add[0]["selector"]  # the add-to-basket feature is found -> it gets its tests
        from backend.agents.test_design import builtin_journeys
        basket = {"url": "https://sweets.test/basket", "slug": "basket", "title": "Basket", "auth": False,
                  "status": 200, "page_type": "cart", "buttons": [], "inputs": [], "forms": [], "links": []}
        shop = [j for j in builtin_journeys([p, basket], limit=40) if j["journey"] == "shop"]
        assert shop and shop[0]["spec"]["cart"] == 'a[href$="/basket"]', shop  # (was: no shopping journey)
    finally:
        page.close()


def test_the_basket_pages_controls_get_no_learned_test():
    from backend.agents.test_design import learned_cases
    empty = {"control": "Empty Basket", "selector": 'a:has-text("Empty Basket")', "effect": "message", "action": "click",
             "tone": "", "message": "confirm: Are you sure you want to empty your basket?", "risk": "safe"}
    basket = {"url": "https://sweets.test/basket", "slug": "basket", "title": "Basket", "auth": False, "status": 200,
              "page_type": "cart", "inputs": [], "forms": [], "links": [], "itemNames": [], "behaviour": [empty],
              "buttons": [{"text": "Empty Basket", "selector": empty["selector"], "tag": "a"}]}
    assert not learned_cases([basket])  # (was: 'Empty Basket' showed no message - the test's basket was empty)
    assert learned_cases([dict(basket, page_type="content", slug="faq")])  # (on another page: still tested)


def test_a_radio_button_under_its_own_label_is_not_covered(browser):
    from backend.agents.discovery import LAYOUT_JS
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.set_content(
            '<!doctype html><html><body style="margin:0"><div style="position:relative">'
            '<input type="radio" id="r1" name="d" value="0.00" style="position:absolute;left:4px;top:4px">'
            '<label for="r1" style="position:relative;display:block;padding:4px 4px 4px 0">Collect (FREE)</label></div>'
            '<button id="b" style="position:relative">Pay</button>'
            '<div style="position:absolute;left:0;top:40px;width:200px;height:40px;background:#fff">banner</div>'
            '</body></html>')
        found = [f["detail"] for f in page.evaluate(LAYOUT_JS) if f["kind"] == "covered"]
        assert not [d for d in found if "0.00" in d], found  # (was: "'0.00' is covered by <label>")
    finally:
        page.close()
