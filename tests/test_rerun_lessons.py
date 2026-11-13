"""What the re-run on AutomationTestStore (runs/automationteststore.com_20261028_114343) still got wrong - each one
fixed and kept fixed here (the pages below are built like the ones there):
  * the home page's item list was a row of brand logos (pictures without names), not the products;
  * the search box's address was guessed for a form a script sends (it has no action): a copy of the home page;
  * the search word was in ONE product (listed twice: 'ABSOLUE ...' and 'Absolue ...'); the shop opened that
    product's page instead of a list, and the tests read the 'Bestsellers' list beside it as the search results;
  * tab links without data-toggle ('#review' in <ul class="nav nav-tabs">, <base href> = the home page) were
    reported as broken links;
  * a fixed 'Back to top' button 'gave no response': it was only ever clicked at the top of the page;
  * the cart page's own boxes and forms exist only while the cart holds an item: 26 tests could not find them;
  * ONE site-wide test case (all input values, all links) failed the features of every page;
  * a repair pointed the missing 'Guest Checkout' choice at 'Register Account' (the choices share one name)."""
import re
import time

import pytest

from backend import registry

PIC = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='40'/%3E"


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

    from backend.observe import DIALOG_INIT_JS
    contexts = []

    def make(pages: dict):
        ctx = browser.new_context(viewport={"width": 1366, "height": 900})
        ctx.add_init_script(DIALOG_INIT_JS)

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


def test_a_row_of_logos_without_names_is_not_the_item_list(site):
    from backend.agents.discovery import ITEMS_JS
    names = ["Skinsheen Bronzer Stick", "Benefit Bella Bamba", "Viva Glam Lipstick", "Nail Lacquer"]
    cards = "".join(f'<div class="col-md-3"><a class="prdocutname" href="/p/{n}">{name}</a><a href="/p/{n}">'
                    f'<img src="{PIC}" width="80" height="40"></a><div class="price">${n}9.50</div></div>'
                    for n, name in enumerate(names, start=1))
    logos = "".join(f'<li><div class="image"><a href="/brand/{n}"><img src="{PIC}" width="80" height="40"></a></div></li>'
                    for n in range(1, 11))  # (10 pictures: more cards than the 4 products - but no names)
    page = site({"/": f'<!doctype html><html><body><h1>Shop</h1><div class="thumbnails list-inline">{cards}</div>'
                      f'<ul id="brandcarousal">{logos}</ul></body></html>'})
    page.goto("http://shop.test/")
    assert page.evaluate(ITEMS_JS, False).get("names") == names


def test_the_search_box_is_followed_only_when_its_form_says_where_it_goes():
    from backend.agents.discovery import _probe_word, _search_url
    box = {"name": "filter_keyword", "id": "filter_keyword", "type": "text", "placeholder": "Search Keywords"}
    by_script = {"forms": [{"method": "get", "action": "", "hidden": [["filter_category_id", "0"]], "fields": [box]}]}
    assert _search_url(by_script, "https://shop.test/", "night") is None  # (was: the home page again, with ?filter_...)
    real = {"forms": [{"method": "get", "action": "index.php", "hidden": [["rt", "product/search"]],
                       "fields": [dict(box, name="keyword")]}]}
    assert _search_url(real, "https://shop.test/", "night") == "https://shop.test/index.php?rt=product/search&keyword=night"
    # the word it searches for is in 2 items (one match may open that item's page instead of the results page)
    assert _probe_word(["Silk Eye Shadow", "Night Repair Serum", "Amber Night Perfume"]) == "night"
    assert _probe_word([]) == "a"


def test_the_search_word_is_in_two_different_items_whatever_their_case():
    from backend.agents.test_design import site_search_word
    pages = [{"itemLinks": {"links": [{"text": "ABSOLUE EYE PRECIOUS CELLS"}, {"text": "BENEFIT GIRL MEETS PEARL"}]}},
             {"itemLinks": {"links": [{"text": "Absolue Eye Precious Cells"}, {"text": "Benefit Bella Bamba"},
                                      {"text": "Skinsheen Bronzer Stick"}]}}]
    assert site_search_word(pages).lower() == "benefit"  # (was 'ABSOLUE': ONE product, listed twice)


def _item(name, text, side):
    lis = "".join(f'<li class="col-xs-12"><a class="productname" href="/index.php?rt=product/product&product_id={i}">'
                  f'{n}</a> <span>$9.90</span></li>' for i, n in side)
    return (f'<!doctype html><html><body><div class="row"><div class="col-md-9"><h1>{name}</h1><p>{text}</p></div>'
            f'<div class="col-md-3"><div class="sidewidt"><h2>Bestsellers</h2><ul class="side_prd_list">{lis}</ul>'
            '</div></div></div></body></html>')


def test_a_search_that_opens_its_only_match_is_judged_on_that_items_page(site):
    from backend.agents.script_generator import RESULT_HELPERS
    ns = {"re": re, "pytest": pytest}
    exec(RESULT_HELPERS, ns)
    ns["_settle"] = lambda page: page.wait_for_load_state()
    items = ["/index.php?rt=product/product&{id}"]
    side = [(2, "Absolute Anti-Age Treatment"), (3, "Absolue Eye Precious Cells"), (4, "Total Moisture Cream")]
    page = site({"/index.php?rt=product/product&product_id=3": _item("Absolue Eye Precious Cells", "An eye cream.", side),
                 "/index.php?rt=product/product&product_id=2": _item("Absolute Anti-Age Treatment", "A day cream.", side),
                 "/index.php?rt=product/search&keyword=absolue": "<h1>Search</h1><p>1 product</p>"})
    page.goto("http://shop.test/index.php?rt=product/product&product_id=3")  # (where the shop went for 'absolue')
    assert ns["_item_landing"](page, "absolue", items) == "Absolue Eye Precious Cells"
    assert ns["_item_landing"](page, "cream", items) == ""  # an item's page, but not named with the word
    page.goto("http://shop.test/index.php?rt=product/search&keyword=absolue")
    assert ns["_item_landing"](page, "absolue", items) == ""  # the results page: its list is read
    # a result without the word in its name must mention it on ITS OWN page - the 'Bestsellers' beside it don't count
    other = "http://shop.test/index.php?rt=product/product&product_id=2"
    assert ns["_mentions"](page, other, "absolue")  # (how it was: the list beside it 'mentioned' the word)
    assert not ns["_mentions"](page, other, "absolue", items)
    assert ns["_mentions"](page, "http://shop.test/index.php?rt=product/product&product_id=3", "absolue", items)


def test_tab_links_in_a_tab_list_are_tabs_even_without_data_toggle(site):
    from backend.agents.discovery import EXTRACT_JS, _sections
    url = "http://shop.test/index.php?rt=product/product&product_id=50"
    tabs = "".join(f'<li><a href="#{t}">{n}</a></li>' for t, n in (("description", "Description"), ("review", "Reviews (0)"),
                                                                    ("producttag", "Tags:")))
    panes = "".join(f'<div class="tab-pane" id="{t}">{t}</div>' for t in ("description", "review", "producttag"))
    page = site({"/index.php?rt=product/product&product_id=50":
                 f'<!doctype html><html><head><base href="http://shop.test/"></head><body><h1>Eye Cream</h1>'
                 f'<ul class="nav nav-tabs" id="myTab">{tabs}</ul><div class="tab-content">{panes}</div></body></html>'})
    page.goto(url)
    data = page.evaluate(EXTRACT_JS)
    assert not [s for s in _sections(data["links"], url, "shop.test") if s["section"] in ("review", "producttag")]
    assert {"Reviews (0)", "Tags:"} <= {b["text"] for b in data["buttons"] if b.get("kind") == "tab"}  # (tested as tabs)


def test_a_floating_back_to_top_button_is_tried_from_further_down_the_page(site):
    from backend.agents.discovery import EXTRACT_JS
    from backend.observe import Explorer
    page = site({"/": '<!doctype html><html><body><h1>Shop</h1>' + "<p>Text of the page.</p>" * 300 +
                      '<a id="gotop" href="#" style="position:fixed;right:10px;bottom:10px">Back to top</a><script>'
                      'document.getElementById("gotop").onclick = e => { e.preventDefault(); window.scrollTo(0, 0); };'
                      '</script></body></html>'})
    ex = Explorer(EXTRACT_JS, lambda pg, ms=0: pg.wait_for_timeout(200), time.time() + 120)
    ev = ex._try(page, "http://shop.test/", {"lazy": False, "itemLinks": {}},
                 {"name": "Back to top", "text": "Back to top", "selector": "#gotop", "action": "click"}, None, "safe")
    assert ev.get("effect") == "scroll", ev  # (was 'nothing': at the top of the page it cannot move anything)


def _page(url, slug, **kw):
    return dict({"url": url, "slug": slug, "title": slug.title(), "auth": False, "status": 200, "page_type": "content",
                 "buttons": [], "inputs": [], "forms": [], "links": [], "itemNames": [], "behaviour": []}, **kw)


SEARCH = {"tag": "input", "type": "text", "name": "filter_keyword", "selector": "#filter_keyword", "label": "Search Keywords",
          "placeholder": "Search Keywords", "role": "textbox"}
COUNTRY = {"tag": "select", "type": "select-one", "name": "country_id", "selector": "#estimate_country", "label": "Country",
           "role": "combobox", "options": [{"value": "1", "text": "Afghanistan"}, {"value": "2", "text": "Albania"}]}
COUPON = {"tag": "input", "type": "text", "name": "coupon", "selector": "#coupon_coupon", "label": "Coupon:", "role": "textbox"}


def test_the_cart_pages_own_controls_get_no_test_that_starts_with_an_empty_cart():
    from backend.agents.test_design import CART_STATE, builtin_checks, data_cases
    home = _page("https://s.test/", "home", inputs=[SEARCH])
    cart = _page("https://s.test/index.php?rt=checkout/cart", "cart", page_type="cart", inputs=[SEARCH, COUNTRY, COUPON])
    used = " ".join(c["element"] for c in builtin_checks([home, cart]))
    assert "#estimate_country" not in used and "#coupon_coupon" not in used
    assert not data_cases(cart)
    reg = registry.build([home, cart], {})
    registry.link_tests(reg, [])
    registry.record_outcomes(reg, [], results=[])
    coupon = next(f for f in reg["features"].values() if f.get("selector") == "#coupon_coupon")
    assert coupon["status"] == "unresolved" and coupon["why"] == CART_STATE  # (not tested - and why)


def _r(file, test, outcome, error="", checks=1):
    return {"nodeid": f"{file}::{test}", "file": file, "test": test, "outcome": outcome, "error": error, "checks": checks}


def test_a_site_wide_case_judges_each_feature_by_its_own_single_tests():
    """ONE case 'Input boxes handle wrong values' failed every box of the site, ONE 'Every link works' every list -
    because of a box / a link somewhere else. Now each box is judged by the values typed into IT, each list by the
    links of ITS items; a test that could not even find its box proves nothing about the box (inconclusive)."""
    login = _page("https://s.test/login", "login", inputs=[
        {"tag": "input", "type": "text", "name": "loginname", "selector": "#loginname", "label": "Login Name", "role": "textbox"}])
    contact = _page("https://s.test/contact", "contact", inputs=[
        {"tag": "textarea", "type": "textarea", "name": "enquiry", "selector": "#enquiry", "label": "Enquiry", "role": "textbox"}])
    search = _page("https://s.test/search", "search", inputs=[
        {"tag": "input", "type": "text", "name": "postcode", "selector": "#postcode", "label": "Postcode", "role": "textbox"}])
    links = [{"href": f"https://s.test/item/{n}", "text": f"Item {n}"} for n in (1, 2, 3)]
    shop = _page("https://s.test/shop", "shop", page_type="listing", links=links,
                 itemLinks={"selector": "div.card a", "links": links})
    reg = registry.build([login, contact, search, shop], {})
    checks = [{"id": f"data_{k}_{v}", "page": p, "selector": s} for p, k, s in
              (("login", "loginname", "#loginname"), ("contact", "enquiry", "#enquiry"), ("search", "postcode", "#postcode"))
              for v in ("valid", "sql")]
    cases = [{"tc_id": "TC-IN", "id": "site_input_values", "title": "Input boxes handle wrong values", "checks": checks,
              "execution_status": "Failed", "actual_result": "2 of 6 failed"},
             {"tc_id": "TC-L", "id": "site_links", "title": "Every link works", "execution_status": "Failed",
              "actual_result": "1 of 4 failed"}]
    from backend.agents.script_generator import link_test_id
    results = [_r("test_login_data.py", "test_data_loginname_valid", "passed"),
               _r("test_login_data.py", "test_data_loginname_sql", "passed"),
               _r("test_contact_data.py", "test_data_enquiry_valid", "passed"),
               _r("test_contact_data.py", "test_data_enquiry_sql", "failed",
                  "AssertionError: The 'Enquiry' box: the attack text ran as a script", 1),
               _r("test_search_data.py", "test_data_postcode_valid", "failed",
                  "AssertionError: the box should be visible\nError: element(s) not found\n"
                  "waiting for locator(\"#postcode\").first", 0),
               _r("test_search_data.py", "test_data_postcode_sql", "passed")]
    results += [_r("test_all_links.py", f"test_link[{link_test_id(l['href'], False)}]", "passed") for l in links]
    results += [_r("test_all_links.py", "test_section_link[sec_1_review]", "failed",
                   "AssertionError: The link 'Reviews' points to #review, but that page has no such part")]
    registry.link_tests(reg, cases)
    registry.record_outcomes(reg, cases, results=results)
    f = {x.get("selector"): x for x in reg["features"].values() if x["level"] == "control"}
    assert f["#loginname"]["status"] == "verified"  # (was 'failed': another page's box failed)
    assert f["#enquiry"]["status"] == "failed" and "script" in f["#enquiry"]["why"]
    assert f["#postcode"]["status"] == "inconclusive" and "locator" in f["#postcode"]["why"]
    items = next(x for x in reg["features"].values() if x["kind"] == "items")
    assert items["status"] == "verified"  # its 3 item links work (was 'failed': a #review link elsewhere)
    # a page that loaded too slowly once and passed on the retry (flaky) never fails its feature
    results[0] = dict(results[0], outcome="failed", flaky=True, error="TimeoutError: Page.goto: Timeout 30000ms exceeded.")
    registry.record_outcomes(reg, cases, results=results)
    assert reg["features"][f["#loginname"]["id"]]["status"] == "verified"


def test_a_repair_never_points_a_missing_choice_at_another_choice_of_its_group():
    from backend.agents.self_healing import _find_new_selector
    register = {"tag": "input", "type": "radio", "name": "account", "selector": "#accountFrm_accountregister",
                "label": "Register Account"}
    guest = dict(register, selector="#accountFrm_accountguest", label="Guest Checkout")
    assert _find_new_selector("input", guest, None, {"inputs": [register]}) is None  # (was '#accountFrm_accountregister')
    assert _find_new_selector("input", guest, None, {"inputs": [register, dict(guest, selector="#guest")]}) == "#guest"


def test_a_form_workflow_that_finds_none_of_its_boxes_fails_instead_of_passing(site):
    """'Fill the whole Update form' PASSED on an empty cart: every box was missing, so every box was skipped."""
    from backend.agents.script_generator import journeys_script
    fields = [{"selector": s, "kind": "type", "value": "Hello test", "name": n, "shown": "Hello test"}
              for s, n in (("#coupon_coupon", "Coupon"), ("#estimate_postcode", "Postcode"))]
    case = {"id": "journey_9", "journey": "form", "guest": True, "title": "Fill the whole 'Update' form - not sent",
            "spec": {"url": "http://shop.test/index.php?rt=checkout/cart", "form": "#cart", "fields": fields}}
    ns = {}
    exec(journeys_script([case]), ns)
    page = site({"/index.php?rt=checkout/cart": "<h1>Shopping Cart</h1><p>Your shopping cart is empty!</p>"})
    with pytest.raises(AssertionError, match="Automation form container must resolve once; found 0"):
        ns["test_journey_9"](page, [])
    page = site({"/index.php?rt=checkout/cart": '<h1>Shopping Cart</h1><form id="cart"><input id="coupon_coupon">'
                                                '<input id="estimate_postcode"></form>'})
    ns["test_journey_9"](page, [])  # (the boxes are there: filled, the form is not sent)


def test_a_form_on_the_cart_page_gets_no_fill_the_form_workflow():
    from backend.agents.test_design import builtin_journeys
    boxes = [{"tag": "input", "type": "text", "name": n, "selector": f"#{n}", "label": n.title()} for n in
             ("coupon", "postcode", "city")]
    form = {"index": 0, "selector": "#estimate", "fields": boxes, "submit": {"text": "Estimate", "selector": "#go"}}
    cart = _page("https://s.test/index.php?rt=checkout/cart", "cart", page_type="cart", inputs=boxes, forms=[form])
    contact = _page("https://s.test/contact", "contact", page_type="form", inputs=boxes,
                    forms=[dict(form, selector="#contact", submit={"text": "Send", "selector": "#send"})])
    forms = [c for c in builtin_journeys([cart, contact]) if c.get("journey") == "form"]
    assert [c["spec"]["url"] for c in forms] == ["https://s.test/contact"]


def test_two_different_forms_are_two_checks_even_when_both_are_the_first_form_of_their_page():
    """DemoStore: the account form and the address form were both 'form >> nth=0' (the first form of the page), so the
    address form's validation check was dropped as 'the same control' - its feature was never tested. A form is known
    by its boxes and its button; a footer form with the same boxes on every page is still tested once."""
    from backend.agents.test_design import builtin_checks

    def form_page(url, slug, boxes, button, footer=False):
        fields = [{"tag": "input", "type": "text", "name": b, "selector": f"#{b}", "label": b.title(), "required": True}
                  for b in boxes]
        forms = [{"index": 0, "selector": "form >> nth=0", "fields": fields, "submit": {"text": button, "selector": f"#{button}"}}]
        buttons = [{"text": button, "selector": f"#{button}", "type": "submit", "in_form": True}]
        if footer:
            news = [{"tag": "input", "type": "email", "name": "news", "selector": "#news", "label": "E-mail", "required": True},
                    {"tag": "input", "type": "text", "name": "who", "selector": "#who", "label": "Name", "required": True}]
            forms.append({"index": 1, "selector": "form >> nth=1", "fields": news, "submit": {"text": "Join", "selector": "#join"}})
            fields, buttons = fields + news, buttons + [{"text": "Join", "selector": "#join", "type": "submit", "in_form": True}]
        return _page(url, slug, auth=True, page_type="form", inputs=fields, buttons=buttons, forms=forms)

    account = form_page("https://s.test/account", "account", ["name", "email", "phone"], "save", footer=True)
    addresses = form_page("https://s.test/addresses", "addresses", ["street", "city", "pin"], "save_address", footer=True)
    forms = [c for c in builtin_checks([account, addresses]) if "submitting it empty" in c["title"]]
    assert sorted(c["page"] for c in forms if "#news" not in c["element"]) == ["account", "addresses"]  # (was: account only)
    assert len([c for c in forms if "#news" in c["element"]]) == 1  # the footer form: one check for the whole site


def test_a_page_that_did_not_load_in_time_is_no_website_defect_and_one_problem_is_one_finding(tmp_path):
    """The final re-run said Not Ready because 2 pages 'did not load' - both were 20 s timeouts while the test machine
    was busy. And one blocked third-party script on 28 pages was 28 findings."""
    from backend.agents.failure_analysis import failure_analysis_agent
    issues = [{"type": "page_failed", "url": "https://s.test/p/50", "detail": "Page.goto: Timeout 20000ms exceeded."},
              {"type": "page_failed", "url": "https://s.test/gone", "detail": "HTTP 500"}]
    issues += [{"type": "failed_request", "url": f"https://s.test/p/{n}", "detail": "net::ERR_BLOCKED_BY_ORB → https://cdn.x/a.js"}
               for n in range(28)]
    out = failure_analysis_agent({"url": "https://s.test/", "results": [], "test_cases": [], "crawl_issues": issues,
                                  "log": [], "run_dir": str(tmp_path)})  # (its failures.json: not in the project)
    crawl = [f for f in out["failures"] if f["source"] == "crawler"]
    slow = next(f for f in crawl if "Timeout" in f["error"])
    assert slow["category"] == "timeout" and slow["severity"] not in ("high", "critical")
    assert next(f for f in crawl if f["error"] == "HTTP 500")["category"] == "product_defect"  # (an error page IS one)
    script = [f for f in crawl if "ORB" in f["error"]]
    assert len(script) == 1 and len(script[0]["pages"]) == 28


def test_the_choice_test_checks_the_choices_on_the_page_and_says_which_are_missing(site, capsys):
    from playwright.sync_api import expect

    from backend.agents.script_generator import _radio_test
    page = site({"/login": '<!doctype html><html><body><form><label><input type="radio" name="account" id="register" '
                           'value="register"> Register Account</label></form></body></html>'})
    ns = {"URL": "http://shop.test/login", "expect": expect, "_settle": lambda p: None, "_pick": lambda box: box.check(),
          "_inconclusive": lambda reason: print(f"[qa-inconclusive] {reason}")}
    exec("\n".join(_radio_test("choice", "Choices", {"radios": ["#register", "#guest"]})), ns)
    ns["test_choice"](page)  # (was: a 10 s wait for '#guest', then an error)
    out = capsys.readouterr().out
    assert "[qa-inconclusive] the choice(s) ['#guest']" in out  # (only the missing one; '#register' was tested)
