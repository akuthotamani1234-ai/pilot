"""The run the user watched live (automationexercise.com, Nov 2, 2026, 22:21, visible Chrome, OpenAI): 'Not Ready' with
28 'website bugs' - checked one by one, almost all were the tool's own mistakes:
  * the visible browser's red caption bar was TEXT of the page: 'Pressing Enter' changed the page's text, so the
    search helper thought Enter had searched and never clicked the search button -> a false 'a search for nonsense
    still shows 34 items' (checked by hand: the button shows 0). A caption could also make 'nothing happened' look
    like a change;
  * one real but cosmetic problem - Google Fonts asked for over http:// on https pages, blocked by the browser - failed
    a journey, 3 smoke checks and 9 'no JavaScript errors' checks, 'high' (the 'Not Ready'), and the crawl counted
    its three fonts as three problems (an address was cut at its first comma);
  * the errors of an API address's own error page (/api/createAccount answers 405) were website bugs;
  * your own test's script matched 'Blue Top' twice (a script mistake) and was never repaired: the AI had called it a
    test mistake, and only script errors / lost elements went to self-healing;
  * the AI saw 42 features on one page, 2 more than allowed: the whole answer was asked for again (paid)."""
import ast
from pathlib import Path

import pytest

from backend.agents.failure_analysis import PASSIVE_MIXED, failure_analysis_agent, healable, same_message

FONT = ("Mixed Content: The page at 'https://shop.test/{p}' was loaded over HTTPS, but requested an insecure stylesheet "
        "'http://fonts.googleapis.com/css?family={f}'. This request has been blocked; the content must be served over "
        "HTTPS.")


def _conftest(name):
    """A constant of templates/conftest.py (read, not imported: importing it would patch Playwright)."""
    tree = ast.parse(Path("backend/templates/conftest.py").read_text(encoding="utf-8"))
    return next(n.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name)


def test_the_caption_of_a_watched_test_is_no_text_of_the_page():
    from playwright.sync_api import sync_playwright
    js = _conftest("CAPTION_JS").value
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            page = b.new_page()
            page.set_content("<h2>All products</h2><input id=q placeholder='Search Product'>")
            before = page.locator("body").inner_text()
            for msg in ("test_check_2  |  Typing 'zzqx' into #q", "test_check_2  |  Pressing Enter in #q"):
                page.locator("#q").evaluate(js, msg)
                assert page.locator("body").inner_text() == before  # (was: the caption's words changed it)
            shown = page.evaluate("getComputedStyle(document.getElementById('__qa_caption'), '::after').content")
            assert "Pressing Enter in #q" in shown  # (a person watching still reads it)
            assert page.get_by_text("Pressing Enter").count() == 0
        finally:
            b.close()


@pytest.mark.parametrize("msg, passive", [
    (FONT.format(p="", f="Roboto:400,300,700"), True),
    ("Mixed Content: The page at 'https://shop.test/' was loaded over HTTPS, but requested an insecure element "
     "'http://shop.test/img/a.jpg'. This request was automatically upgraded to HTTPS.", True),
    ("Mixed Content: The page at 'https://shop.test/' was loaded over HTTPS, but requested an insecure script "
     "'http://cdn.test/app.js'. This request has been blocked.", False),  # (a script can break the page: an error)
    ("Uncaught TypeError: Cannot read properties of null", False)])
def test_an_insecure_font_or_picture_is_a_warning_an_insecure_script_an_error(msg, passive):
    assert bool(PASSIVE_MIXED.search(msg)) is passive
    tests_rule = _conftest("PASSIVE_MIXED").args[0].value  # (the generated tests use the same rule)
    assert tests_rule == PASSIVE_MIXED.pattern


def test_one_insecure_font_problem_is_one_low_finding_and_api_pages_are_no_bugs(tmp_path):
    pages = ["", "products", "view_cart"]
    issues = [{"type": "console_error", "url": f"https://shop.test/{p}", "detail": FONT.format(p=p, f=f)}
              for p in pages for f in ("Roboto:400,300,400italic", "Open+Sans:400,800", "Abel")]
    issues += [{"type": "console_error", "url": "https://shop.test/api/createAccount",
                "detail": "Failed to load resource: the server responded with a status of 404 ()"},
               {"type": "failed_request", "url": "https://shop.test/api/createAccount",
                "detail": "HTTP 404 → https://shop.test/static/rest_framework/js/csrf.js"}]
    app_map = [{"url": f"https://shop.test/{p}", "status": 200} for p in pages] + [
        {"url": "https://shop.test/api/createAccount", "status": 405}]
    found = failure_analysis_agent({"run_dir": str(tmp_path), "url": "https://shop.test/", "results": [],
                                    "crawl_issues": issues, "test_cases": [], "app_map": app_map, "log": []})["failures"]
    fonts = [f for f in found if "Mixed Content" in f["error"]]
    assert len(fonts) == 1 and len(fonts[0]["pages"]) == 3, fonts  # (was: 3 findings - one per font)
    assert fonts[0]["severity"] == "low" and "https://" in fonts[0]["explanation"]
    api = [f for f in found if "createAccount" in f["page_url"]]
    assert api and all(f["category"] == "infrastructure" and f["severity"] == "low" for f in api), api
    assert len({same_message(FONT.format(p="x", f=f)) for f in ("Roboto:400,300", "Abel")}) == 1


def test_a_script_that_matched_two_elements_is_repaired_even_when_the_ai_called_it_a_test_mistake():
    strict = "Error: strict mode violation: locator(\"text=Blue Top\") resolved to 2 elements"
    assert healable({"source": "test", "category": "test_mistake", "error": strict})
    assert healable({"source": "test", "category": "locator", "error": "x"})
    assert not healable({"source": "test", "category": "test_mistake", "error": "AssertionError: expected 'Done'"})
    assert not healable({"source": "test", "category": "product_defect", "error": strict})
    assert not healable({"source": "crawler", "category": "locator", "error": strict})


def test_a_magnifier_button_only_searches_and_an_api_page_has_no_features():
    from backend import registry
    from backend.actions import action_risk
    assert action_risk("fa fa search btn btn default btn lg", "#submit_search") == "safe"  # (was: protected - 'submit')
    assert action_risk("Save search", "#save") == "protected"  # (its words still decide)
    assert action_risk("", "#submit_search") == "protected"    # (no words, no icon: the code name decides, as before)
    box = {"selector": "#search_product", "type": "text", "placeholder": "Search Product", "name": "search"}
    products = {"url": "https://shop.test/products", "slug": "products", "status": 200, "title": "Products",
                "inputs": [box], "buttons": [{"selector": "#submit_search", "text": "fa fa search btn btn default btn lg"}],
                "links": [], "forms": []}
    api = {"url": "https://shop.test/api/createAccount", "slug": "api_create", "status": 405, "title": "Create Account",
           "inputs": [{"selector": "#content", "type": "text", "label": "Content:"}],
           "buttons": [{"selector": "#options", "text": "OPTIONS"}], "links": [], "forms": []}
    reg = registry.build([products, api], {})
    names = {f.get("name") for f in reg["features"].values()}
    assert not names & {"OPTIONS", "Content:"}, names  # (was: 'features' of an API address's error page)


def test_a_busy_page_keeps_the_first_40_features_the_ai_saw():
    from backend.vision import PageSeen
    seen = PageSeen.model_validate({"purpose": "Shop", "features": [{"name": f"F{n}", "kind": "button", "does": "x"}
                                                                    for n in range(42)],
                                    "messages": [f"m{n}" for n in range(25)]})
    assert len(seen.features) == 40 and len(seen.messages) == 20  # (was: rejected - the AI was asked again)
