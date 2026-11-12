"""What the first run on a website the tool had never seen got wrong (automationexercise.com, Nov 2, 2026,
runs/automationexercise.com_20261102_171249) - each one fixed and kept fixed here:
  * one 'Mixed Content' console message (its text names the page) became 93 findings: 73 from the crawl, 17 'no
    JavaScript errors' page checks, 3 more - it is ONE problem of the website;
  * the API addresses listed as links (/api/createAccount answers POST, not a page visit: HTTP 405) were 'broken links'
    and a 'critical' page that failed;
  * a 'busy' answer of the server (HTTP 503) was a website bug;
  * the search box is not in a form: pressing Enter does nothing, only its button searches - 'a search for something
    that does not exist still shows 34 items' (checked by hand: the button shows 0);
  * the run had no ad blocking yet: Google's full-screen ad (#google_vignette) lay over pages during the tests."""
import pytest

from backend.agents.failure_analysis import failure_analysis_agent

MIXED = ("Mixed Content: The page at '{page}' was loaded over HTTPS, but requested an insecure element "
         "'http://automationexercise.com/static/images/home/girl1.jpg'. This request was automatically upgraded.")


def _analyse(tmp_path, results=(), issues=()):
    return failure_analysis_agent({"run_dir": str(tmp_path), "url": "https://shop.test/", "results": list(results),
                                   "crawl_issues": list(issues), "test_cases": [], "app_map": [], "log": []})["failures"]


def test_one_console_message_on_many_pages_is_one_finding(tmp_path):
    pages = [f"https://shop.test/{p}" for p in ("", "products", "view_cart", "login")]
    issues = [{"type": "console_error", "url": u, "detail": MIXED.format(page=u)} for u in pages]
    results = [{"nodeid": f"test_site.py::test_no_console_errors[p{n}]", "file": "test_site.py",
                "test": f"test_no_console_errors[p{n}]", "outcome": "failed", "error_type": "AssertionError",
                "url": u, "error": f"E   AssertionError: JavaScript errors on {u}:\nE     {MIXED.format(page=u)}"}
               for n, u in enumerate(pages)]
    found = _analyse(tmp_path, results, issues)
    crawl = [f for f in found if f["source"] == "crawler"]
    tests = [f for f in found if f["source"] == "test"]
    assert len(crawl) == 1 and len(crawl[0]["pages"]) == 4, crawl  # (was: 4 findings - one per page)
    assert len(tests) == 1 and len(tests[0]["pages"]) == 4 and "Seen on 4 pages" in tests[0]["explanation"], tests
    assert [f["id"] for f in found] == list(range(len(found)))
    other = dict(results[0], nodeid="test_site.py::test_no_console_errors[x]", test="test_no_console_errors[x]",
                 error="E   AssertionError: JavaScript errors on https://shop.test/x:\nE     JS exception: boom")
    assert len([f for f in _analyse(tmp_path, results + [other]) if f["source"] == "test"]) == 2  # another error


def test_an_api_address_and_a_busy_server_are_no_broken_pages(tmp_path):
    issues = [{"type": "page_failed", "url": "https://shop.test/api/createAccount", "detail": "HTTP 405"},
              {"type": "failed_request", "url": "https://shop.test/brand/Madame",
               "detail": "HTTP 503 → https://shop.test/get_product_picture/41"},
              {"type": "failed_request", "url": "https://shop.test/x", "detail": "HTTP 404 → https://shop.test/a.js"}]
    found = {f["error"][:8]: f for f in _analyse(tmp_path, issues=issues)}
    assert found["HTTP 405"]["category"] == "infrastructure" and "API address" in found["HTTP 405"]["explanation"]
    assert found["HTTP 503"]["category"] == "infrastructure" and found["HTTP 503"]["severity"] == "low"
    assert found["HTTP 404"]["category"] == "product_defect"  # a missing file is still a bug


def test_a_click_that_got_a_busy_server_answer_is_no_website_bug():
    from backend.agents.failure_analysis import classify
    err = ("E   AssertionError: Clicking 'Add to cart' caused errors:\nE     HTTP 503 from the website's server: "
           "GET /add_to_cart/1 (after: Click 'Add to cart')")
    r = {"nodeid": "t::a", "file": "test_checks.py", "test": "test_check_7", "outcome": "failed", "error": err,
         "error_type": "AssertionError"}
    assert classify(r)[0] == "infrastructure"


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


SHOP = """<!doctype html><html><body><h2 class="title">ALL PRODUCTS</h2>
<input type="text" id="search_product" placeholder="Search Product">
<button type="button" id="submit_search" onclick="location.href='/products?search=' + encodeURIComponent(
  document.getElementById('search_product').value)"><i class="fa fa-search"></i></button>
<div class="productinfo">Blue Top</div><div class="productinfo">Men Tshirt</div></body></html>"""


def test_a_search_box_without_a_form_is_sent_with_its_button(browser):
    from backend.agents.script_generator import RESULT_HELPERS
    ctx = browser.new_context()
    ctx.route("http://shop.test/**", lambda route: route.fulfill(
        status=200, content_type="text/html",
        body=SHOP if "search=" not in route.request.url else "<h2>SEARCHED PRODUCTS</h2><p>No products</p>"))
    page = ctx.new_page()
    try:
        page.goto("http://shop.test/products")
        ns = {}
        exec("import re\nimport pytest\n" + RESULT_HELPERS, ns)
        box = page.locator("#search_product")
        box.fill("zzqx-no-such-item")
        ns["_submit_search"](page, box)
        page.wait_for_load_state()
        assert "search=zzqx-no-such-item" in page.url, page.url  # (was: Enter only - the page never searched)
        assert page.locator(".productinfo").count() == 0
    finally:
        ctx.close()


def test_the_test_cases_sheet_lists_the_steps_each_case_really_did():
    from backend.excel import executed_steps
    case = {"tc_id": "TC-1", "id": "journey_1", "tests": ["test_journey_1"], "files": ["test_journeys.py"]}
    r = {"file": "test_journeys.py", "test": "test_journey_1", "nodeid": "test_journeys.py::test_journey_1",
         "outcome": "failed", "live_steps": [{"text": "Open /products", "ok": True},
                                             {"text": "Type 'Top' into 'Search Product'", "ok": True},
                                             {"text": "Check failed: no results", "ok": False}]}
    text = executed_steps(case, [r])
    assert text.splitlines() == ["1. ✓ Open /products", "2. ✓ Type 'Top' into 'Search Product'",
                                 "3. ✗ Check failed: no results"], text
