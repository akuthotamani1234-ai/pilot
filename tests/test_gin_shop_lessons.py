"""What the run on ginandjuice.shop (runs/ginandjuice.shop_20261101_203622, logged in with the test account) got
wrong - each one fixed and kept fixed here (the pages below are built like the ones there):
  * 'My account' lists one 'Order details' link per order: the menu journey clicked the FIRST one for every order;
  * the order page's headings are all <h4> ('Billing address'): 'the order page should have a heading' failed;
  * 'Add to cart' (its only box: a quantity list, which always has a choice) got 'submitting it empty is rejected';
  * at phone width the category buttons in a row you swipe sideways were reported 'outside the screen';
  * the blog's search was asked for a product word ('LIMITED'): no post has it - that is no bug; and its result
    cards all say 'VIEW POST' (not the post's name): the post's own page must say the word;
  * the login journey failed twice, for two reasons: the first try's login was refused, the retry logged in and met
    the real JavaScript error - the report showed the first reason;
  * 'VIEW POST' (a link to a blog post) was blocked as a protected action: 'post' as in 'send' - and then 'the
    first item VIEW POST opened a page that shows A HAIRY DAY': the post's name is on its card, not on its link.
(Checked by hand: the JavaScript error on every order page, the search that finds nothing with capital letters and
the 720px wide page on a phone are real website bugs - those findings stay.)"""
import pytest

H4_ORDER = ('<!doctype html><html><body><h4>Order details:</h4><p>Order {n}</p><h4>Billing address</h4>'
            '<p>Carlos Montoya</p></body></html>')
ACCOUNT = ('<!doctype html><html><body><h1>My account</h1><nav><a href="/catalog">PRODUCTS</a></nav><table>'
           + "".join(f'<tr><td>Order {n}</td><td><a href="/order/details?orderId={n}">Order details</a></td></tr>'
                     for n in (1, 2, 3)) + '</table></body></html>')


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def site(browser):
    """A made-up website: site({address (path + query): html}) -> a browser page that shows it."""
    from urllib.parse import urlparse
    contexts = []

    def make(pages: dict):
        ctx = browser.new_context(viewport={"width": 1366, "height": 900})

        def answer(route):
            u = urlparse(route.request.url)
            body = pages.get(u.path + ("?" + u.query if u.query else ""))
            route.fulfill(status=200 if body else 404, body=body or "<h1>Not found</h1>", content_type="text/html")
        ctx.route("http://shop.test/**", answer)
        contexts.append(ctx)
        return ctx.new_page()
    yield make
    for ctx in contexts:
        ctx.close()


def _shop(site):
    pages = {"/my-account": ACCOUNT, "/catalog": "<h1>Products</h1>"}
    pages.update({f"/order/details?orderId={n}": H4_ORDER.format(n=n) for n in (1, 2, 3)})
    return site(pages)


def _run(case, page):
    from backend.agents.script_generator import journeys_script
    ns = {}
    exec(journeys_script([case]), ns)
    ns[f"test_{case['id']}"](page, [])


def test_the_menu_journey_opens_each_order_by_its_own_address(site):
    links = [{"text": "Order details", "href": f"http://shop.test/order/details?orderId={n}",
              "to": f"http://shop.test/order/details?orderId={n}", "name": "Order details"} for n in (3, 2, 1)]
    _run({"id": "journey_5", "journey": "navigate", "title": "Move through the website by clicking its menu",
          "spec": {"start": "http://shop.test/my-account", "links": links, "logged_in": True}}, _shop(site))
    # (was: "'Order details' opened ...orderId=1 instead of ...orderId=3")


def test_the_order_journey_accepts_an_order_page_with_only_small_headings(site):
    _run({"id": "journey_3", "journey": "orders", "title": "Open an order from 'My account' and see its details",
          "spec": {"url": "http://shop.test/my-account", "href": "http://shop.test/order/details?orderId=2",
                   "name": "Order details", "subs": []}}, _shop(site))
    # (was: 'the order page should have a heading' - it looked for <h1> / <h2> only)


def _form_page(forms):
    return {"url": "https://shop.test/catalog/product?productId=1", "slug": "product", "title": "Product",
            "auth": False, "status": 200, "page_type": "product", "buttons": [], "inputs": [], "links": [],
            "itemNames": [], "behaviour": [], "forms": forms}


def test_a_form_whose_only_box_is_a_list_gets_no_empty_form_test():
    from backend.agents.test_design import rule_based_cases
    qty = {"name": "quantity", "id": "", "type": "select-one", "selector": 'select[name="quantity"]', "required": True,
           "label": "10"}
    cart = {"index": 1, "selector": "#addToCartForm", "action": "/catalog/cart", "method": "post",
            "submit": {"text": "ADD TO CART", "selector": "#addToCartForm button"}, "fields": [qty]}
    ids = {c["id"] for c in rule_based_cases(_form_page([cart]))}
    assert "form1_required_validation" not in ids, ids
    note = dict(cart, index=0, selector="#contact", submit={"text": "Send", "selector": "#contact button"},
                fields=[qty, {"name": "message", "id": "message", "type": "textarea", "selector": "#message",
                              "required": True, "label": "Message"}])
    assert "form0_required_validation" in {c["id"] for c in rule_based_cases(_form_page([note]))}  # (still tested)


def test_buttons_in_a_row_you_swipe_are_not_outside_the_screen(browser):
    from backend.agents.discovery import LAYOUT_JS
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        cats = "".join(f'<a href="/c/{n}" style="display:inline-block;width:120px">{n}</a>'
                       for n in ("All", "Accessories", "Books", "Gin", "Juice"))
        page.set_content('<!doctype html><html><body style="margin:0"><div style="overflow-x:auto;white-space:nowrap">'
                         f'{cats}</div><div style="width:720px"><a href="/a">Menu A</a>'
                         '<a href="/b" style="margin-left:600px">Menu B</a></div></body></html>')
        found = page.evaluate(LAYOUT_JS)
        off = [f["detail"] for f in found if f["kind"] == "off screen"]
        assert not [d for d in off if any(n in d for n in ("Books", "Gin", "Juice"))], off
        assert any("Menu B" in d for d in off), found  # (sticking out of the page itself: still reported)
        assert any(f["kind"] == "horizontal scroll" for f in found), found
    finally:
        page.close()


def test_the_blog_search_looks_for_a_word_of_the_blogs_own_posts():
    from backend.agents.test_design import section_search_word, site_search_word
    names = ["FRUIT SLICER (LIMITED EDITION)", "LIMITED EDITION COCKTAIL SHAKER", "JUICE EXTRACTOR", "PURPLE HAT GIN"]
    catalog = {"url": "https://shop.test/catalog", "headings": ["PRODUCTS"],
               "itemLinks": {"links": [{"text": n, "href": f"https://shop.test/catalog/product?productId={i}"}
                                       for i, n in enumerate(names)]}}
    posts = {2: "THE THIRD WHEEL", 3: "A HAIRY DAY", 4: "THE COMPLAINT"}
    blog = {"url": "https://shop.test/blog", "headings": ["BLOG"],
            "itemLinks": {"links": [{"text": "VIEW POST", "href": f"https://shop.test/blog/post?postId={n}"} for n in posts]}}
    pages = [catalog, blog] + [{"url": f"https://shop.test/blog/post?postId={n}", "headings": [t, "COMMENTS"]}
                               for n, t in posts.items()]
    word = site_search_word(pages)
    assert word == "LIMITED"
    assert section_search_word(catalog, pages, word) == "LIMITED"
    assert section_search_word(blog, pages, word).lower() in " ".join(posts.values()).lower()


BLOG = {"url": "http://shop.test/blog", "slug": "blog", "title": "Blog", "links": [], "forms": [], "buttons": [],
        "itemNames": [], "site_word": "HAIRY", "site_cards": ["div.blog-post a.button"], "site_items": [],
        "inputs": [{"tag": "input", "type": "text", "name": "search", "id": "", "label": "", "selector": 'input[name="search"]',
                    "placeholder": "Search the blog..."}]}
POST_CARD = '<div class="blog-post"><img alt=""><a class="button" href="/blog/post?postId={n}">VIEW POST</a></div>'


def _blog(site, found):
    results = "".join(POST_CARD.format(n=n) for n in found) or "<p>No results</p>"
    return site({"/blog": '<h1>Blog</h1><form action="/blog/"><input name="search" placeholder="Search the blog...">'
                          f'<button>Search</button></form><section class="blog-list">{POST_CARD.format(n=3)}</section>',
                 "/blog/?search=HAIRY": f'<h1>Blog</h1><input name="search"><section class="blog-list">{results}</section>',
                 "/blog/post?postId=3": "<h1>A Hairy Day</h1><p>A story.</p>",
                 "/blog/post?postId=4": "<h1>The Complaint</h1><p>Another story.</p>"})


def test_search_results_that_all_say_view_post_are_judged_on_their_own_pages(site):
    from backend.agents.script_generator import template_script
    from backend.agents.test_design import rule_based_cases
    cases = [c for c in rule_based_cases(BLOG) if c["id"] == "search_finds_item"]
    assert cases, [c["id"] for c in rule_based_cases(BLOG)]
    ns = {}
    exec(template_script(BLOG, cases), ns)
    ns["test_search_finds_item"](_blog(site, [3]), [])  # (was: "did not list it: the results are ['VIEW POST']")
    with pytest.raises(AssertionError, match="did not list it"):
        ns["test_search_finds_item"](_blog(site, [4]), [])  # a post that doesn't say 'hairy': still a failure


def _guard(monkeypatch):
    """The generated tests' click guard (templates/conftest.py: _risky and its patterns), with this run's patterns
    in production - only those parts, so the guard is not installed in this test process."""
    import ast
    import os
    import re
    from pathlib import Path

    from backend.actions import PROTECTED, SAFE_TEXT, WRITE
    monkeypatch.setenv("QA_PROTECTED_RX", PROTECTED.pattern)
    monkeypatch.setenv("QA_SAFE_TEXT_RX", SAFE_TEXT.pattern)
    monkeypatch.setenv("QA_WRITE_RX", WRITE.pattern)
    tree = ast.parse(Path("backend/templates/conftest.py").read_text(encoding="utf-8"))
    want = {"PROTECTED_RX", "TEST_ACCOUNT_RX", "SAFE_TEXT_RX", "UNSAFE_LINK_RX", "MONEY_RX", "WRITE_RX", "_risky"}
    nodes = [n for n in tree.body if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in want)
             or (isinstance(n, ast.FunctionDef) and n.name in want)]
    ns = {"re": re, "os": os}
    exec(compile(ast.Module(nodes, []), "conftest.py", "exec"), ns)
    return ns["_risky"]


def test_a_link_that_says_post_or_share_only_opens_a_page(monkeypatch):
    risky = _guard(monkeypatch)
    assert not risky(["VIEW POST", "", "", "/blog/post?postId=3"])  # (was: Blocked - a protected action)
    assert not risky(["Share", "", "", "https://social.example/share?u=1"])
    assert risky(["POST COMMENT", "", "", ""])  # a button that sends: still blocked
    assert risky(["Send", "", "", ""])
    assert risky(["Log out", "", "", "/logout"])  # pay / delete / log out: even a link
    assert risky(["Buy now", "", "", "/product/1"])
    assert risky(["Delete", "", "", "/items"])


def test_blog_posts_whose_links_say_view_post_open_with_the_name_on_their_card(site):
    from backend.agents.script_generator import JOURNEY_HELPERS, LINES_JS, RESULT_HELPERS
    from backend.items import items_script
    titles = {2: "The Third Wheel", 3: "A Hairy Day", 4: "The Complaint"}
    cards = "".join(f'<div class="blog-post"><a href="/blog/post?postId={n}"><img alt=""></a><h2>{t}</h2>'
                    f'<p>A story about the shop.</p><a class="button" href="/blog/post?postId={n}">View post</a></div>'
                    for n, t in titles.items())
    pages = {"/blog": f'<h1>Blog</h1><section class="blog-list">{cards}</section>'}
    pages.update({f"/blog/post?postId={n}": f"<h1>{t}</h1><p>The story.</p>" for n, t in titles.items()})
    case = {"id": "items_open_4", "kind": "items", "title": "Items of /blog open with their own name",
            "spec": {"url": "http://shop.test/blog", "hints": ["section.blog-list > div.blog-post a.button"],
                     "picks": ["first", "middle", "last"]}}
    header = ["import re", "import pytest", "from playwright.sync_api import expect", "", JOURNEY_HELPERS,
              RESULT_HELPERS, f"LINES_JS = {LINES_JS!r}", ""]
    ns = {}
    exec(items_script([case], header), ns)
    ns["test_items_open_4"](site(pages))  # (was: "the first item 'VIEW POST' opened a page that shows 'A HAIRY DAY'")
    pages["/blog/post?postId=3"] = "<h1>Gin Cocktail Recipes</h1><p>Another post.</p>"  # the WRONG post opens
    # (since Nov 2: a card whose link only says 'View post' is named by its own title - 'A Hairy Day')
    with pytest.raises(AssertionError, match="'A Hairy Day' opened a page that shows 'Gin Cocktail Recipes'"):
        ns["test_items_open_4"](site(pages))


def test_a_test_that_fails_again_for_another_reason_reports_the_retry():
    from backend.agents.executor import _merge_retry
    login = "E   AssertionError: Login with the test account did not work: the login form is still shown"
    js = "E   AssertionError: Logging in and using the app caused JavaScript errors:\nE     JS exception: null"
    results = [{"nodeid": "t.py::a", "outcome": "failed", "error": login, "screenshot": "a1.png"},
               {"nodeid": "t.py::b", "outcome": "failed", "error": js, "screenshot": "b1.png"},
               {"nodeid": "t.py::c", "outcome": "failed", "error": login, "screenshot": "c1.png"}]
    _merge_retry(results, {"t.py::a": {"outcome": "failed", "error": js, "screenshot": "a2.png", "trace": "a.zip"},
                           "t.py::b": {"outcome": "failed", "error": js, "screenshot": "b2.png", "trace": "b.zip"},
                           "t.py::c": {"outcome": "passed", "error": "", "trace": "c.zip"}})
    a, b, c = results
    assert (a["error"], a["first_error"], a["screenshot"], a["trace"]) == (js, login, "a2.png", "a.zip")
    assert (b["error"], b["screenshot"], b["trace"]) == (js, "b1.png", "b.zip") and "first_error" not in b  # same reason
    assert c["flaky"] and c["error"] == login and c["rerun_outcome"] == "passed"  # passed on the retry: first failure kept
