"""What the runs on www.demoblaze.com (runs/www.demoblaze.com_20261102_053252) and practicesoftwaretesting.com
(runs/practicesoftwaretesting.com_20261102_053239) got wrong - each one fixed and kept fixed here (the pages below are
built like the ones there):
  * 'the next page lists the same items': the test clicked 'Previous' (demoblaze #prev2, the toolshop's '«') - every
    button of a pager counts as 'next', and the items test took the first one;
  * 'Every button can be clicked': the toolshop's '«' on page 1 sits in li.page-item.disabled (pointer-events: none):
    'li.page-item.disabled intercepts pointer events';
  * "'Samsung galaxy s6' was clicked, its page shows 'STORE'": demoblaze's product name is an <h2> (no <h1>), its title
    just 'STORE'; on the toolshop (a single-page app) the product's <h1> came ~2 s after the click, the test read the
    page before ('shows Practice Software Testing');
  * the toolshop's 'Testing Guide' panel lay over every page after the home page ('Next →' covered at phone width on
    13 pages): exploring clicked it, the site stored testing-split-screen-active=true in localStorage - and the
    products picked for comparison made /comparison show buttons a new visitor never sees (2 failed tests);
  * a search with 2 results "could not be read": the toolshop's cards ARE links (<a class="card">), the list's
    address was 'a.card a.card' - which matches nothing;
  * 7 'website bugs' on 3 of the toolshop's product pages: it rebuilt its data during the crawl (its API listed them
    at 05:32 and answered 'not found' for them a minute later) - the tests knew it ('[data changed]'), the report not.
Their re-runs (runs/www.demoblaze.com_20261102_060357, runs/practicesoftwaretesting.com_20261102_060118):
  * demoblaze 'The cart shows no total': it shows 'Total' / '360' - no currency sign; its price column too ('360');
  * the toolshop's JavaScript error on /checkout ('ERROR TypeError: Cannot read properties of null') was 'an error of
    the test script': the words 'TypeError' were looked for anywhere in the test's output;
  * the toolshop's cart came ~1.5 s after the click on the cart icon: the test read the product page ('Bolt Cutters
    is in the cart' - its own box) and then a cart without a total; and 'Back did not return to the list' (it came);
  * 'Show live shop activity' opens its panel - 'Server-Sent Events feed' in it was taken for a message ('sent');
  * 'Compare' (its button turns from outline to filled) and 'Sign in with Google' (it opens a window) were 'controls
    that gave no visible response'.
The second re-run (runs/practicesoftwaretesting.com_20261102_062226) and the first run with the AI (OpenAI
gpt-4o-mini, runs/sweetshop.netlify.app_20261102_062700):
  * "its card says 46.5, its page shows ['46.50']" - as if another price: it is the same price, written differently
    ('$46.5' on the card - that slip is real, and small);
  * 'Seen on 38 pages': one page (/checkout) that logged its error 38 times;
  * the AI's 9 test cases were all thrown away: one had a single step, one gave its test data as fields.
(Checked by hand, real: demoblaze at phone width - the cart page's 'Products' heading covers the 2nd line of the menu
('About us' -> 'About'), the menu button is covered by a <div> (a tap does nothing); the toolshop with its Testing
Guide open at phone width - its 'Next →' lies under the 'live shop activity' button, its close button over the
'Documentation' link; its API answers HTTP 500 for the related products of a product that does not exist.)"""
import time

import pytest


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def site(browser):
    """A made-up website: site({path: html}) -> a browser page on http://shop.test (a real origin: localStorage)."""
    from urllib.parse import urlparse
    contexts = []

    def make(pages: dict, **kw):
        ctx = browser.new_context(**dict({"viewport": {"width": 1366, "height": 900}}, **kw))

        def answer(route):
            body = pages.get(urlparse(route.request.url).path)
            route.fulfill(status=200 if body else 404, body=body or "<h1>Not found</h1>",
                          content_type="text/html; charset=utf-8")
        ctx.route("http://shop.test/**", answer)
        contexts.append(ctx)
        return ctx.new_page()
    yield make
    for ctx in contexts:
        ctx.close()


def _helpers():
    from backend.agents.script_generator import CART_HELPERS, JOURNEY_HELPERS, LINES_JS, RESULT_HELPERS
    ns = {}
    exec("\n".join(["import re", "import pytest", "from playwright.sync_api import expect", "", JOURNEY_HELPERS,
                    CART_HELPERS, RESULT_HELPERS, f"LINES_JS = {LINES_JS!r}", ""]), ns)  # (our own generated test code)
    return ns


def test_the_next_page_is_next_not_previous():
    from backend.items import _next_control, pager_next
    blaze = {"buttons": [{"text": "Previous", "kind": "next", "selector": "#prev2"},
                         {"text": "Next", "kind": "next", "selector": "#next2"}], "links": []}
    assert _next_control(blaze) == "#next2"  # (was: '#prev2')
    shop = {"buttons": [{"text": t, "kind": "next", "selector": f'[data-test="pagination-{s}"]'}
                        for t, s in (("«", "prev"), ("1", "1"), ("2", "2"), ("»", "next"))], "links": []}
    assert _next_control(shop) == '[data-test="pagination-next"]'
    assert pager_next([{"text": "«", "kind": "next", "selector": "#p"}, {"text": "2", "kind": "next", "selector": "#2"}],
                      lambda b: b["text"])["selector"] == "#2"  # (no Next: page 2, never '«')


def test_a_pager_button_that_cannot_be_clicked_is_not_clicked(site):
    from backend.agents.discovery import EXTRACT_JS
    from backend.agents.test_design import safe_buttons
    from backend.auth import login_form
    page = site({"/": '<!doctype html><html><head><title>Tools</title><style>.page-item.disabled .page-link'
                      '{pointer-events:none;color:#999}</style></head><body><h1>Tools</h1><ul class="pagination">'
                      '<li class="page-item disabled"><button type="button" class="page-link" data-test="pagination-prev"'
                      ' aria-label="Previous"><span aria-hidden="true">«</span></button></li><li class="page-item">'
                      '<button type="button" class="page-link" data-test="pagination-next" aria-label="Next">'
                      '<span aria-hidden="true">»</span></button></li></ul>'
                      '<button id="hello">Say hello</button></body></html>',
                 "/login": '<!doctype html><html><head><title>Login</title></head><body><h1>Sign in</h1>'
                           '<input id="email" type="email" name="email"><input id="pw" type="password">'
                           '<div role="button" id="go" aria-disabled="true">Log in</div></body></html>'})
    page.goto("http://shop.test/")
    data = page.evaluate(EXTRACT_JS)
    by = {b["text"]: b for b in data["buttons"]}
    assert by["«"]["inert"] and not by["»"]["inert"], data["buttons"]
    p = dict(data, url="http://shop.test/", slug="home", title="Tools", auth=False, status=200, behaviour=[])
    assert "«" not in {b["text"] for b in safe_buttons(p)}  # (was: clicked - 'li.page-item.disabled intercepts')
    page.goto("http://shop.test/login")  # a login button greyed out until its boxes are filled in: still THE button
    data = page.evaluate(EXTRACT_JS)
    form = login_form(dict(data, url="http://shop.test/login", final_url="http://shop.test/login"))
    assert form and form["submit"] == next(b["selector"] for b in data["buttons"] if b["text"] == "Log in"), data["buttons"]


def test_the_item_pages_name_is_its_h2_and_a_single_page_app_is_waited_for(site):
    ns = _helpers()
    page = site({"/prod": '<!doctype html><html><head><title>STORE</title></head><body><nav><h4>PRODUCT STORE</h4></nav>'
                          '<div class="modal" style="display:none"><h5>Log in</h5></div><h2 class="name">Samsung galaxy '
                          's6</h2><h3>$360 *includes tax</h3><div id="footc"><h4>About Us</h4></div></body></html>',
                 "/spa": '<!doctype html><html><head><title>Practice Software Testing</title></head><body><div id="app">'
                         '</div><script>setTimeout(() => { document.getElementById("app").innerHTML = "<h1>Combination '
                         'Pliers</h1>"; document.title = "Combination Pliers - Practice Software Testing"; }, 1500)'
                         '</script></body></html>'})
    page.goto("http://shop.test/prod")
    assert ns["_product_name"](page, "Samsung galaxy s6") == "Samsung galaxy s6"  # (was: 'STORE')
    page.goto("http://shop.test/spa")
    assert ns["_product_name"](page, "Combination Pliers") == "Combination Pliers"  # (was: 'Practice Software Testing')
    page.goto("http://shop.test/prod")
    t = time.time()
    assert ns["_product_name"](page, "Nokia lumia 1520") == "Samsung galaxy s6"  # another item's page: still told
    assert time.time() - t < 15


def test_exploring_forgets_what_its_clicks_made_the_site_remember(site):
    from backend.agents.discovery import EXTRACT_JS
    from backend.observe import Explorer
    page = site({"/": '<!doctype html><html><head><title>Tools</title></head><body><h1>Tools</h1>'
                      '<button id="guide" onclick="localStorage.setItem(\'testing-split-screen-active\', \'true\'); '
                      'document.getElementById(\'panel\').hidden = false">Testing Guide</button>'
                      '<div id="panel" hidden><p>Step 1 of 18</p></div></body></html>'})
    page.goto("http://shop.test/")
    page.evaluate("() => localStorage.setItem('auth-token', 'abc')")  # (e.g. the test account's login: stays)
    entry = dict(page.evaluate(EXTRACT_JS), url="http://shop.test/", slug="home", title="Tools", lazy=False)
    ex = Explorer(EXTRACT_JS, lambda pg, ms=0: pg.wait_for_timeout(200), time.time() + 120)
    ex.explore(page, "http://shop.test/", entry)
    assert [b for b in entry.get("behaviour", []) if b["control"] == "Testing Guide"], entry.get("behaviour")  # (tried)
    kept = page.evaluate("() => Object.keys(localStorage)")
    assert kept == ["auth-token"], kept  # (was: testing-split-screen-active=true -> its panel over every later page)


def test_a_gone_item_is_no_website_bug_but_its_server_error_still_is(tmp_path):
    from backend.agents.failure_analysis import failure_analysis_agent
    old, api = "https://shop.test/product/01M6CNFFNP6D0R182K02V2Q48X", "https://api.shop.test/products/01M6CNFFNP6D0R182K02V2Q48X"
    (tmp_path / "results_pytest_output.txt").write_text(  # (what the tests print: templates/conftest.py)
        f"[data changed] {old} no longer exists - testing the same kind of page: https://shop.test/product/01M6CRXD\n",
        encoding="utf-8")
    issues = [{"type": "failed_request", "url": old, "detail": f"HTTP 404 → {api}"},
              {"type": "failed_request", "url": old, "detail": f"HTTP 500 → {api}/related"},
              {"type": "console_error", "url": old, "detail": "ERROR yi"},
              {"type": "console_error", "url": "https://shop.test/cart", "detail": "ERROR yi"}]
    out = failure_analysis_agent({"url": "https://shop.test/", "run_dir": str(tmp_path), "crawl_issues": issues,
                                  "results": [], "test_cases": [], "app_map": []})["failures"]
    got = {(f["error"][:8], tuple(f["pages"])): f["category"] for f in out}
    assert got == {("HTTP 404", (old,)): "infrastructure",  # (was: a website bug - the site had rebuilt its data)
                   ("HTTP 500", (old,)): "product_defect",  # a server error stays one (checked by hand: a real bug)
                   ("ERROR yi", (old,)): "infrastructure",
                   ("ERROR yi", ("https://shop.test/cart",)): "product_defect"}, got  # (not merged with the gone one)


def test_the_websites_javascript_typeerror_is_no_error_of_the_test_script():
    from backend.agents.failure_analysis import classify
    js = ("test_site.py:71: in test_no_console_errors\nE   AssertionError: JavaScript errors on https://shop.test/checkout:\n"
          "E     ERROR TypeError: Cannot read properties of null (reading 'cart_items')")
    assert classify({"outcome": "failed", "error_type": "AssertionError", "error": js})[0] != "test_defect"  # (was)
    assert classify({"outcome": "failed", "error_type": "TypeError",
                     "error": "E   TypeError: 'NoneType' object is not subscriptable"})[0] == "test_defect"
    assert classify({"outcome": "failed", "error": "E   NameError: name 'rows' is not defined"})[0] == "test_defect"


def test_a_name_joined_by_a_hyphen_is_no_message_tone():
    from backend.observe import tone
    assert tone("Server-Sent Events feed") == ""  # (was 'ok': 'sent' - the live feed panel became a 'message')
    assert tone("Message sent") == "ok" and tone("Product added to shopping cart.") == "ok"
    assert tone("error-free delivery") == "" and tone("An error occurred") == "error"


def test_a_cart_total_and_price_without_a_currency_are_read(site):
    ns = _helpers()
    page = site({"/cart": '<!doctype html><html><body><h2>Products</h2><table><thead><tr><th>Pic</th><th>Title</th>'
                          '<th>Price</th><th>x</th></tr></thead><tbody><tr><td></td><td>Samsung galaxy s6</td><td>360</td>'
                          '<td><a href="#">Delete</a></td></tr></tbody></table><h2>Total</h2><h3>360</h3>'
                          '<p>Total items</p><p>3</p></body></html>'})
    page.goto("http://shop.test/cart")
    assert ns["_cart_total"](page) == 360.0  # (was: None - 'The cart shows no total')
    assert ns["_line_price"](ns["_cart_row"](page, "Samsung galaxy s6")) == 360.0


def test_the_cart_of_a_single_page_app_is_read_when_it_is_shown(site):
    ns = _helpers()
    cart = ('<h2>Cart</h2><table><tr><th>Item</th><th>Quantity</th><th>Price</th></tr><tr><td>Bolt Cutters</td>'
            '<td><input type=number value=1></td><td>$48.41</td></tr><tr><td>Total</td><td></td><td>$48.41</td></tr></table>')
    page = site({"/product": '<!doctype html><html><body><header><a id="cart" href="/checkout">Cart</a></header><main '
                             'id="app"><div class="product"><h1>Bolt Cutters</h1><input type=number value=1><button>Add '
                             'to cart</button><span>$48.41</span></div></main><script>document.getElementById("cart")'
                             '.onclick = e => { e.preventDefault(); history.pushState({}, "", "/checkout"); setTimeout('
                             '() => { document.getElementById("app").innerHTML = ' + repr(cart).replace("'", '"') +
                             '; }, 1500); };</script></body></html>'})
    page.goto("http://shop.test/product")
    ns["_leaving"](page)
    page.locator("#cart").click()
    ns["_arrived"](page)
    row = ns["_cart_row"](page, "Bolt Cutters")
    assert row is not None and row.evaluate("e => e.tagName") == "TR"  # (was: the PRODUCT page's box - 'in the cart')
    assert ns["_cart_total"](page) == 48.41


def test_a_control_that_changes_its_own_look_or_opens_a_window_is_no_dead_control(site):
    from backend.agents.script_generator import learned_script
    ns = {}
    exec(learned_script([]), ns)
    page = site({"/": '<!doctype html><html><head><style>.on{background:blue}</style></head><body><h1>Pliers</h1>'
                      '<button id="compare" class="btn btn-outline" onclick="this.className = \'btn btn-filled\'">Compare'
                      '</button><button id="google" onclick="window.open(\'/popup\')">Sign in with Google</button>'
                      '<button id="dead">Notify me</button></body></html>', "/popup": "<h1>Sign in</h1>"})
    L = lambda sel, name: {"url": "http://shop.test/", "opener": None, "selector": sel, "name": name,  # noqa: E731
                           "effect": "nothing", "action": "click", "tone": "", "message": "", "guest": True}
    ns["_check_learned"](page, [], L("#compare", "Compare"))  # (was: 'gave no visible response')
    ns["_check_learned"](page, [], L("#google", "Sign in with Google"))
    assert len(page.context.pages) == 1  # (the window it opened is closed again)
    with pytest.raises(AssertionError, match="gave no visible response"):
        ns["_check_learned"](page, [], L("#dead", "Notify me"))  # a control that does nothing: still told


def test_the_same_price_written_differently_is_said_so_and_one_page_counts_once(site, tmp_path):
    from backend.agents.failure_analysis import _severity, failure_analysis_agent
    from backend.agents.script_generator import JOURNEY_HELPERS, LINES_JS, RESULT_HELPERS
    from backend.items import items_script
    cards = "".join(f'<div class="card"><a href="/p/{n}"><h5>{t}</h5></a><span>${p}</span></div>'
                    for n, (t, p) in enumerate((("Sheet Sander", "58.48"), ("Belt Sander", "73.59"),
                                                ("Cordless Drill 12V", "46.5"))))
    pages = {"/tools": f'<!doctype html><html><body><h1>Power Tools</h1><div class="grid">{cards}</div></body></html>'}
    pages.update({f"/p/{n}": f"<h1>{t}</h1><p>$<span>{p}</span></p>" for n, (t, p) in
                  enumerate((("Sheet Sander", "58.48"), ("Belt Sander", "73.59"), ("Cordless Drill 12V", "46.50")))})
    case = {"id": "items_open_4", "kind": "items", "title": "Items of /tools open with their own name and price",
            "spec": {"url": "http://shop.test/tools", "hints": ["div.grid > div.card a"], "picks": ["last"]}}
    ns = {}
    exec(items_script([case], ["import re", "import pytest", "from playwright.sync_api import expect", "",
                               JOURNEY_HELPERS, RESULT_HELPERS, f"LINES_JS = {LINES_JS!r}", ""]), ns)
    with pytest.raises(AssertionError, match="the same price, written differently") as e:
        ns["test_items_open_4"](site(pages))  # (was: "its card says 46.5, its page shows ['46.50']" - as if another)
    assert _severity("product_defect", {"test": "test_items_open_4"}, str(e.value))[0] == "low"
    issues = [{"type": "console_error", "url": "https://shop.test/checkout", "detail": "ERROR TypeError: x"}] * 38
    f = failure_analysis_agent({"url": "https://shop.test/", "run_dir": str(tmp_path), "crawl_issues": issues,
                                "results": [], "test_cases": [], "app_map": []})["failures"][0]
    assert f["pages"] == ["https://shop.test/checkout"] and "Seen on" not in f["explanation"]  # (was: 'Seen on 38 pages')


def test_an_ai_case_that_does_not_fit_is_left_out_not_all_of_them(monkeypatch):
    import json

    from backend import llm
    from backend.agents import test_design
    page = {"url": "https://x.test/login", "slug": "login", "title": "Login", "itemNames": [], "forms": [],
            "buttons": [{"text": "Login", "selector": "#go"}], "inputs": [{"type": "password", "selector": "#p"}],
            "links": []}
    answer = [{"title": "Login with a wrong password is refused", "steps": ["Open the login page", "Type a wrong password"],
               "expected": "An error is shown", "test_data": {"email": "test@example.com", "password": "wrong"}},
              {"title": "Open the about page", "steps": ["Open the about page"]}]  # (one step: does not fit)
    calls = []
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, **k: calls.append(prompt) or json.dumps(answer))
    cases = test_design.ai_flows([page])
    assert [c["title"] for c in cases] == [answer[0]["title"]] and len(calls) == 1  # (was: all thrown away -> rules)
    assert cases[0]["test_data"] == "email=test@example.com, password=wrong"


def test_cards_that_are_links_are_read_also_with_only_two_results(site):
    from backend.agents.discovery import EXTRACT_JS, ITEMS_JS
    names = ["Combination Pliers", "Pliers", "Bolt Cutters", "Long Nose Pliers", "Slip Joint Pliers", "Claw Hammer"]
    card = ('<a class="card" href="/product/{i}"><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" width="40" '
            'height="40" alt=""><div class="card-body"><h5 data-test="product-name">{n}</h5></div><span>${p}</span></a>')
    grid = lambda items: ('<!doctype html><html><head><title>Toolshop</title></head><body><h1>Toolshop</h1><div '  # noqa: E731
                          'class="container"><div class="col-md-9">' + "".join(card.format(i=i, n=n, p=f"{10 + i}.99")
                                                                         for i, n in items) + '</div></div></body></html>')
    page = site({"/": grid(enumerate(names)), "/search": grid([(9, "Bolt Cutters"), (11, "Nuts and bolts")])})
    page.goto("http://shop.test/")
    sel = page.evaluate(EXTRACT_JS)["itemLinks"]["selector"]
    assert page.locator(sel).count() == len(names), sel  # (was: 'a.card a.card' - nothing)
    page.goto("http://shop.test/search")
    got = page.evaluate(ITEMS_JS, {"mark": True, "hints": [sel]})
    assert got.get("names") == ["Bolt Cutters", "Nuts and bolts"], got  # (was: "no list of results could be read")
