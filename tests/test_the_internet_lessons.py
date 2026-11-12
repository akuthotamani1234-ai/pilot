"""What the run on the-internet.herokuapp.com (runs/the-internet.herokuapp.com_20261101_232934) got wrong - each one
fixed and kept fixed here (the pages below are built like the ones there):
  * 122 'broken pages' were files on its Download page ('.txt', '.md', '.sql' ...): 'Page.goto: Download is starting';
  * an analytics script of ANOTHER company (optimizely.com, its address does not resolve) failed on every page: 77
    findings 'website bug' - its address carries the page's address in its query, so it looked like the site's own -
    and 76 pages 'JavaScript errors' ('Failed to load resource: net::ERR_NAME_NOT_RESOLVED');
  * three 'click here' links to the same page with other settings (?mode=random) were tested as a list of items;
  * a read-only box that only shows a text ('You cannot change me') was tested as a box that opens a calendar;
  * the empty login form's answer ('Your username is invalid!') came from a slow server after more than 4 s: 'no
    error message was shown';
  * '/infinite_scroll/16' - a piece of text the endless list loads - was a page 'without a <title>'.
(Checked by hand, real: the broken links /about /contact-us /portfolio /gallery /users/N, links to #edit / #delete,
the JavaScript error page, the broken images, the empty large form that is accepted, the pages too wide for a phone.)"""
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
    """A made-up website: site({address (path + query): html or (status, html)}) -> a browser page that shows it."""
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


def test_another_companys_tracker_is_one_third_party_finding_not_a_website_bug(tmp_path):
    from backend.agents.failure_analysis import failure_analysis_agent
    tracker = "https://298279967.log.optimizely.com/event?a=1&n=https%3A%2F%2Fshop.test%2F{p}&t={t}"
    issues = [{"type": "failed_request", "url": f"https://shop.test/{p}", "page": p,
               "detail": "net::ERR_NAME_NOT_RESOLVED → " + tracker.format(p=p, t=n)} for n, p in enumerate(("a", "b", "c"))]
    issues.append({"type": "failed_request", "url": "https://shop.test/a", "page": "a",
                   "detail": "HTTP 500 → https://shop.test/api/cart?x=1"})
    out = failure_analysis_agent({"url": "https://shop.test/", "results": [], "test_cases": [], "crawl_issues": issues,
                                  "run_dir": str(tmp_path)})
    crawl = out["failures"]
    tracked = [f for f in crawl if "optimizely" in f["error"]]
    assert len(tracked) == 1 and tracked[0]["category"] == "third_party" and len(tracked[0]["pages"]) == 3, crawl
    assert next(f for f in crawl if "api/cart" in f["error"])["category"] == "product_defect"  # (the site's own)


def test_a_failed_load_of_another_websites_file_is_no_console_error_of_this_one(browser):
    from backend.agents.discovery import _foreign_load_error
    from backend.safety import Scope
    page = browser.new_page()
    try:
        seen = []
        page.on("console", lambda m: seen.append(m) if m.type == "error" else None)
        page.set_content('<h1>Shop</h1><img src="http://qa-tracker.invalid/pixel.gif">')
        page.wait_for_timeout(1500)
        loads = [m for m in seen if m.text.startswith("Failed to load resource")]
        assert loads, [m.text for m in seen]
        assert _foreign_load_error(loads[0], Scope("http://shop.test/"))  # (a tracker of another website)
        assert not _foreign_load_error(loads[0], Scope("http://qa-tracker.invalid/"))  # (the site's own file: kept)
    finally:
        page.close()


def test_click_here_links_to_the_same_page_are_no_item_list():
    from backend.items import _lists
    here = "https://shop.test/shifting_content/menu"
    versions = {"url": here + "?mode=random", "itemLinks": {"selector": "div.example > p a[href]", "links": [
        {"href": here + q, "text": "click here"} for q in ("?mode=random", "?pixel_shift=100", "?mode=random&pixel_shift=100")]}}
    blog = {"url": "https://shop.test/blog", "itemLinks": {"selector": "div.blog-post a.button", "links": [
        {"href": f"https://shop.test/blog/post?postId={n}", "text": "View post"} for n in (1, 2, 3)]}}
    assert _lists([versions, blog]) == [blog]


def test_a_read_only_box_with_a_fixed_text_opens_nothing(browser):
    from backend.agents.discovery import EXTRACT_JS
    page = browser.new_page()
    try:
        page.set_content('<h1>Read-only</h1><label>Always read-only<input id="fixed" value="You cannot change me" readonly>'
                         '</label><label>Departure<input id="date" value="12/05/2026" readonly></label>'
                         '<label>Guests<input id="guests" value="2 Adults" readonly></label>'
                         '<label>Return<input id="empty" readonly></label>')
        opener = {i["selector"]: i["opener"] for i in page.evaluate(EXTRACT_JS)["inputs"]}
        assert opener == {"#fixed": False, "#date": True, "#guests": True, "#empty": True}, opener
    finally:
        page.close()


LOGIN = ('<!doctype html><html><head><title>Login</title></head><body>{flash}<h2>Login Page</h2>'
         '<form id="login" action="/authenticate" method="post"><label>Username<input name="username" id="username">'
         '</label><label>Password<input type="password" name="password" id="password"></label>'
         '<button type="submit">Login</button></form></body></html>')
SLOW_ANSWER = ("<script>setTimeout(() => document.body.insertAdjacentHTML('afterbegin', "
               "'<div id=\"flash\" class=\"flash error\">Your username is invalid!</div>'), 5000)</script>")


def test_a_piece_of_an_endless_list_is_no_page(site):
    """'/infinite_scroll/16' answers <br>text...<a href="/infinite_scroll/17">next page</a> - no <head>, no title."""
    from backend.agents.discovery import FRAGMENT_JS as js
    page = site({"/infinite_scroll/16": '<br>Quo quaerat ab rerum ipsam.<a href="/infinite_scroll/17">next page</a>',
                 "/tiny": "<h1>Contact</h1><p>Write to us.</p>",  # a tiny real page without <head>: a page
                 "/links": '<p>Pick one:</p><a href="/a">A</a> <a href="/b">B</a>'})
    found = {}
    for path in ("/infinite_scroll/16", "/tiny", "/links"):
        page.goto("http://shop.test" + path)
        found[path] = page.evaluate(js)
    assert found == {"/infinite_scroll/16": True, "/tiny": False, "/links": False}, found


def test_the_empty_form_check_waits_for_a_slow_servers_answer(site):
    from backend.agents.script_generator import template_script
    from backend.agents.test_design import rule_based_cases
    p = {"url": "http://shop.test/login", "slug": "login", "title": "Login", "auth": False, "status": 200,
         "page_type": "login", "buttons": [], "links": [], "itemNames": [], "behaviour": [],
         "inputs": [{"tag": "input", "type": "text", "name": "username", "id": "username", "selector": "#username",
                     "label": "Username"},
                    {"tag": "input", "type": "password", "name": "password", "id": "password", "selector": "#password",
                     "label": "Password"}],
         "forms": [{"index": 0, "selector": "#login", "action": "/authenticate", "method": "post",
                    "submit": {"text": "Login", "selector": "#login button"},
                    "fields": [{"name": "username", "id": "username", "type": "text", "selector": "#username",
                                "required": False, "label": "Username"},
                               {"name": "password", "id": "password", "type": "password", "selector": "#password",
                                "required": False, "label": "Password"}]}]}
    # Declare this fixture server's known requirement. Its HTML still lacks native
    # required validation, so this continues to exercise the delayed server reply.
    p["forms"][0]["fields"][0]["required"] = True
    cases = [c for c in rule_based_cases(p) if c["id"] == "form0_required_validation"]
    assert cases
    ns = {}
    exec(template_script(p, cases), ns)
    page = site({"/login": LOGIN.format(flash=""), "/authenticate": LOGIN.format(flash=SLOW_ANSWER)})
    ns["test_form0_required_validation"](page)  # (was: 'Empty form: no error message was shown' after 4 s)
