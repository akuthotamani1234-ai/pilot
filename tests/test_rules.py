"""Rules that decide what the user is told: script checks, failure categories, release gates, test-case schema."""
import pytest

from backend.agents.script_generator import validate_script

OK = "from playwright.sync_api import expect\n\ndef test_a(page):\n    page.goto('https://x.test')\n    expect(page).to_have_title('X')\n"


@pytest.mark.parametrize("code, why", [
    ("import importlib\ndef test_a(page):\n    pass\n", "Banned import"),
    ("from playwright.sync_api import sync_playwright\ndef test_a(page):\n    pass\n", "Banned import"),
    ("import playwright.sync_api\ndef test_a(page):\n    pass\n", "Banned import"),
    ("def test_a(page):\n    getattr(page, 'goto')('x')\n", "Banned call"),
    ("def test_a(page):\n    x = ().__class__\n", "Banned attribute"),
    ("def test_a(page):\n    page.context.route('**/*', lambda r: r.continue_())\n", "Banned attribute"),
    ("def test_a(page):\n    page.context.browser.new_context()\n", "Banned attribute"),
    ("def test_a(page):\n    page.request.post('https://x.test/api', data={})\n", "Banned call"),
    ("def test_a(page):\n    page.wait_for_timeout(60000)\n", "too long"),
    ("import time\ndef test_a(page):\n    time.sleep(3)\n", "Banned attribute"),
    ("def test_a(page):\n    page.locator('#f').set_input_files('C:/Users/me/.env')\n", "in-memory file"),
    ("def test_a(page, request):\n    pass\n", "may not use the fixture"),
    ("def pytest_collection_modifyitems(items):\n    pass\ndef test_a(page):\n    pass\n", "pytest hooks"),
    ("pytest_plugins = ['evil']\ndef test_a(page):\n    pass\n", "Banned name"),
])
def test_generated_code_that_could_escape_the_sandbox_is_refused(code, why):
    assert why in (validate_script(code) or ""), validate_script(code)


def test_normal_generated_code_is_accepted():
    assert validate_script(OK) is None
    assert validate_script("import steps_home\nimport re, json\nfrom urllib.parse import urljoin\n" + OK) is None


@pytest.mark.parametrize("result, category", [
    ({"outcome": "inconclusive", "error": "checked nothing"}, "inconclusive"),
    ({"outcome": "failed", "flaky": True, "error": "AssertionError"}, "flaky"),
    ({"outcome": "failed", "error": "PermissionError: blocked by the test sandbox: subprocess.Popen"}, "test_defect"),
    ({"outcome": "failed", "error_type": "TestTimeout", "error": "TestTimeout"}, "timeout"),
    ({"outcome": "failed", "error": "AssertionError: 'Orders' sent me back to the login page"}, "auth_problem"),
    ({"outcome": "failed", "error": "net::ERR_CONNECTION_REFUSED at https://x.test"}, "infrastructure"),
    # a locator / interaction failure: the test could not use the element - not proof of a website bug (healed)
    ({"outcome": "failed", "error": "Locator.click: Timeout 10000ms exceeded. waiting for locator('#gone')"}, "locator"),
    ({"outcome": "failed", "error_type": "TimeoutError", "error": "Locator.click: <div class=\"cookie\"> intercepts "
      "pointer events"}, "locator"),
    # a hover menu that did not open for the test: its sub-menu is in the page - to review, not a proven bug
    ({"outcome": "failed", "error_type": "AssertionError", "error": "AssertionError: Pointing at it (or clicking its "
      "menu button) showed nothing (no menu / details)"}, "assertion_failure"),
    # the test said why it could not establish the result
    ({"outcome": "inconclusive", "error": "Inconclusive: the box kept 'x' and shows no error"}, "inconclusive"),
    ({"outcome": "failed", "error_type": "AssertionError", "error": "Empty form was accepted"}, "product_defect"),
    ({"outcome": "failed", "error_type": "ValueError", "error": "something odd"}, "inconclusive"),
    ({"outcome": "failed", "error": "APIRequestContext.get: read ECONNRESET"}, "infrastructure"),
    ({"outcome": "failed", "error": "AssertionError: HTTP 429 Too Many Requests"}, "infrastructure"),
    # an exploratory expectation (learned while exploring) that is not met: to review, not a proven website bug
    ({"outcome": "failed", "file": "test_learned.py", "error_type": "AssertionError",
      "error": "AssertionError: 'Open help' did not open its panel"}, "assertion_failure"),
    # ... but an error message, or a control with no visible response, is a website problem
    ({"outcome": "failed", "file": "test_learned.py", "error_type": "AssertionError",
      "error": "AssertionError: 'Add to wishlist': the website said 'Something went wrong'"}, "product_defect"),
    ({"outcome": "failed", "file": "test_learned.py", "error_type": "AssertionError",
      "error": "AssertionError: 'Notify me' gave no visible response (no message, nothing changed)"}, "suspect"),
    # (Step 8: it did nothing while exploring AND in its test - no evidence what it should do: a person looks)
    ({"outcome": "failed", "file": "test_learned.py", "error_type": "AssertionError",
      "error": "AssertionError: Using 'Cart' caused JavaScript errors:\n  JS exception: showcart is not defined"},
     "product_defect"),
    # an AI-written expectation nobody saw while exploring (a message the website shows in an alert box instead):
    # to review, not a website bug - but an AI locator that matches several elements is the script's fault
    ({"outcome": "failed", "file": "test_flows_ai.py", "error_type": "AssertionError",
      "error": "AssertionError: Locator expected to be visible\nActual value: None\nError: element(s) not found"},
     "assertion_failure"),
    ({"outcome": "failed", "file": "test_flows_ai.py", "error_type": "Error",
      "error": "Locator.click: Error: strict mode violation: locator(\"button[aria-label='Close']\") resolved to 4 "
               "elements"}, "locator"),
    # the element the script works with is gone (renamed / moved / removed): the SCRIPT must be repaired ...
    ({"outcome": "failed", "file": "test_learned.py", "error_type": "AssertionError",
      "error": "AssertionError: 'Notify me' should be visible\nLocator expected to be visible\nActual value: None\n"
               "Error: element(s) not found\n[...]\nCall log:\n  - waiting for locator(\"#notify\")"}, "locator"),
    # ... but an expected TEXT that did not appear is a check of the website (an AI guess here: to review)
    ({"outcome": "failed", "file": "test_flows_ai.py", "error_type": "AssertionError",
      "error": "AssertionError: Locator expected to be visible\nError: element(s) not found\nCall log:\n"
               "  - waiting for locator(\"text=Wrong username or password.\")"}, "assertion_failure"),
])
def test_failures_are_classified_from_evidence(result, category):
    from backend.agents.failure_analysis import classify
    assert classify(dict({"file": "test_flows.py", "test": "t"}, **result))[0] == category


def test_ai_answers_are_validated_with_one_corrective_retry(monkeypatch):
    """Structured output: a malformed AI answer is sent back ONCE with what was wrong; an id the AI made up is
    ignored; a second bad answer -> LLMError (the rules take over)."""
    import json

    from backend import llm
    from backend.agents import test_design
    page = {"url": "https://x.test/login", "slug": "login", "title": "Login", "itemNames": [], "forms": [],
            "buttons": [{"text": "Login", "selector": "#go"}], "inputs": [{"type": "password", "selector": "#p"}],
            "links": []}
    good = [{"title": "Login with a wrong password is refused", "steps": ["Open the login page", "Type a wrong password"],
             "expected": "An error is shown"}]
    answers = iter([json.dumps([{"title": "x", "steps": "not a list"}]), json.dumps(good)])
    calls = []
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, **k: calls.append(prompt) or next(answers))
    cases = test_design.ai_flows([page])
    assert [c["title"] for c in cases] == [good[0]["title"]] and len(calls) == 2
    assert "YOUR PREVIOUS ANSWER WAS NOT VALID" in calls[1]
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, **k: "no json at all")
    with pytest.raises(llm.LLMError):
        test_design.ai_flows([page])
    reg = {"features": {"F-1": {"id": "F-1", "level": "control", "name": "EN", "kind": "button", "pages": ["home"],
                                "evidence": {"effect": "panel", "revealed": ["DE", "FR"]}}}}
    labels = [{"id": "F-1", "feature": "Language switch", "category": "settings", "expected": "Other languages show"},
              {"id": "F-999", "feature": "Made up", "category": "other", "expected": "never seen"}]
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, **k: json.dumps(labels))
    assert test_design.ai_feature_labels(reg) == 1 and reg["features"]["F-1"]["ai_feature"] == "Language switch"


def test_the_result_helpers_judge_sort_orders_prices_and_messages():
    """The helpers every generated test uses (script_generator.RESULT_HELPERS), run here as plain Python."""
    import re as _re

    import pytest as _pytest

    from backend.agents.script_generator import RESULT_HELPERS
    ns = {"re": _re, "pytest": _pytest}
    exec(RESULT_HELPERS, ns)
    assert ns["_sort_rule"]("Price: low to high") == ("price", "asc")
    assert ns["_sort_rule"]("Price (High - Low)") == ("price", "desc")
    assert ns["_sort_rule"]("Name (Z - A)") == ("name", "desc") and ns["_sort_rule"]("Name") == ("name", "asc")
    assert ns["_sort_rule"]("Relevance") is None and ns["_sort_rule"]("CO2 rating (A - E)") is None
    cards = ["Red Apple 1\n₹57", "Green Pear 2\n₹94", "Sweet Mango 3\n₹131"]
    assert ns["_in_order"](cards, ("price", "asc"))[0] and not ns["_in_order"](cards[::-1], ("price", "asc"))[0]
    assert ns["_money"]("Total: $1,214.50") == 1214.5 and ns["_money"]("no price") is None
    assert ns["_card_name"]("ECO\nSafety Goggles\nA\n$24.26") == "Safety Goggles"
    assert ns["_tone"]("Please sign in to save favourites") == "login_needed"
    assert ns["_tone"]("Something went wrong - the item could not be saved") == "error"
    assert ns["_tone"]("Added Red Apple 1 to your cart") == "ok"
    assert ns["_tone"]("alert: Product added.") == "ok"  # (what the website said in the browser's alert box)


def test_pages_told_apart_by_their_query_like_index_php_routes():
    """automationteststore.com: every page is /index.php?rt=... - comparing only the path said 'Clicking the first item
    did not open its page' when it did. The query that picks the page counts; tracking / session / currency don't."""
    import re as _re

    from backend.agents.script_generator import JOURNEY_HELPERS
    ns = {"re": _re}
    exec(JOURNEY_HELPERS, ns)
    shop = "https://s.test/index.php?rt=product/category&path=68"
    item = "https://s.test/index.php?rt=product/product&product_id=50"
    assert ns["_page_of"](item) != ns["_page_of"](shop)
    assert ns["_page_of"](item + "&utm_source=x&currency=EUR") == ns["_page_of"](item)
    assert ns["_same_page"](item + "&path=68", item)  # (the website may add more to the address)
    assert not ns["_same_page"]("https://s.test/index.php?rt=product/product&product_id=51", item)
    assert ns["_same_page"]("https://s.test/orders/1001/", "https://s.test/orders/1001")
    assert ns["_key"](item) == ns["_key"](shop) == "/index.php"  # (the path alone: the same KIND of page)


def test_a_dead_control_is_only_a_defect_for_a_control_made_to_do_something():
    """'It did nothing visible' fails a test only for a real action button - a link to the page itself, a box to
    type in, a slider / page arrow or a 'Close' may rightly show nothing (no test: inconclusive in the registry)."""
    from backend.agents.test_design import _must_respond
    assert _must_respond({"tag": "button", "kind": "", "html": '<button id="notify">'}, "Notify me")
    assert _must_respond({"tag": "a", "html": '<a href="#" onclick="add(1)">'}, "Add to cart")  # a link that acts
    assert not _must_respond({"tag": "a", "html": '<a class="nav-link" href="cart.html">'}, "Cart")
    assert not _must_respond({"tag": "input", "type": "text"}, "Username:")
    assert not _must_respond({"tag": "a", "kind": "slide", "html": '<a href="#carousel" role="button">'}, "Next")
    assert not _must_respond({"tag": "button", "kind": "next"}, "Previous")
    assert not _must_respond({"tag": "button"}, "Close")
    assert not _must_respond({"tag": "div", "custom": True}, "Card")
    assert not _must_respond(None, "Unknown")


def test_a_step_the_website_does_not_allow_is_said_next_to_the_pass():
    from backend.excel import case_result
    case = {"tc_id": "TC-1", "tests": ["test_journey_1"], "files": ["test_journeys.py"]}
    res = [{"nodeid": "test_journeys.py::test_journey_1", "file": "test_journeys.py", "test": "test_journey_1",
            "outcome": "passed", "note": "the cart has no quantity control for 'Phone': the quantity step was not possible"}]
    status, detail = case_result(case, res)
    assert status == "Passed" and "not possible on this website: the cart has no quantity control" in detail


def test_the_ai_designs_from_what_exploring_observed(monkeypatch):
    """(was: the AI guessed outcomes - on demoblaze 'Wrong username or password.' on the page, when the website
    answers in an alert box). It gets what really happened; an outcome nobody saw is marked exploratory."""
    import json

    from backend import llm
    from backend.agents import test_design
    page = {"url": "https://x.test/prod/1", "slug": "prod_1", "title": "Phone", "itemNames": [], "forms": [], "inputs": [],
            "links": [], "buttons": [{"text": "Add to cart", "selector": "a.add"}],
            "behaviour": [{"control": "Add to cart", "selector": "a.add", "effect": "message", "tone": "ok",
                           "message": "alert: Product added."},
                          {"control": "Broken", "selector": "#b", "effect": "error", "error": "timeout"}]}
    summary = json.loads(test_design._site_summary([page]))
    assert summary[0]["observed"] == [{"control": "Add to cart", "did": "message", "said": "alert: Product added."}]
    answer = [{"title": "Add the phone to the cart", "steps": ["Open the phone page", "Click 'Add to cart'"],
               "expected": "The website says 'Product added.'"},
              {"title": "Add the phone twice", "steps": ["Open the phone page", "Click 'Add to cart' twice"],
               "expected": "Exploratory: the cart may show the phone twice"}]
    prompts = []
    monkeypatch.setattr(llm, "ask_llm", lambda prompt, **k: prompts.append(prompt) or json.dumps(answer))
    cases = test_design.ai_flows([page])
    assert "alert: Product added." in prompts[0]
    assert [c["type"] for c in cases] == ["end-to-end", "exploratory"]


def test_ai_expected_message_without_evidence_is_marked_exploratory(monkeypatch):
    from backend.agents import test_design

    page = {"url": "https://x.test/", "slug": "home", "title": "Shop", "headings": ["Shop"],
            "forms": [], "inputs": [], "links": [], "buttons": []}
    monkeypatch.setattr(test_design, "ask_structured", lambda *a, **k: [test_design.AICase(
        title="Check the order response", steps=["Open the shop", "Submit the order"],
        expected="The website says 'Order confirmed.'")])

    case = test_design.ai_flows([page])[0]

    assert case["type"] == "exploratory"
    assert case["expected"].startswith("Exploratory:")
    assert "Order confirmed." in case["expected"]


def test_ai_test_code_can_read_what_the_website_said_also_in_an_alert_box(monkeypatch):
    from backend.agents import script_generator as sg
    code = ("import re\nimport pytest\nfrom playwright.sync_api import expect\n\n\n@pytest.mark.guest\n"
            "def test_ai_flow_1(page):\n    \"\"\"Add to cart\"\"\"\n    page.goto('https://x.test/prod/1')\n"
            "    page.locator('a.add').click()\n    assert any('Product added' in m for m in _said(page))\n")
    monkeypatch.setattr(sg, "ask_llm", lambda *a, **k: f"```python\n{code}```")
    flows = [{"id": "ai_flow_1", "title": "Add to cart", "guest": True, "pages": ["prod_1"], "test_data": "",
              "steps": ["Open", "Click"], "expected": "Product added."}]
    out = sg._llm_flows(flows, {"prod_1": {"slug": "prod_1", "url": "https://x.test/prod/1", "buttons": [],
                                           "inputs": [], "forms": [], "links": [],
                                           "behaviour": [{"message":"alert: Product added."}]}})
    assert "def _said(page):" in out and "__qaDialogs" in out and sg.validate_script(out) is None
    assert out.index("from playwright.sync_api import expect") < out.index("def _said(") < out.index("def test_ai_flow_1")


def test_ai_cannot_change_the_category(monkeypatch, tmp_path):
    from backend.agents import failure_analysis as fa
    monkeypatch.setattr(fa, "llm_enabled", lambda: True)
    monkeypatch.setattr(fa, "ask_llm", lambda *a, **k: '[{"id": 0, "category": "test_defect", "explanation": "probably fine"}]')
    out = fa.failure_analysis_agent({"run_dir": str(tmp_path), "url": "https://x.test", "results": [
        {"nodeid": "n", "test": "test_form0_required_validation", "file": "test_home.py", "outcome": "failed",
         "error_type": "AssertionError", "error": "E   AssertionError: Empty form was accepted"}]})
    f = out["failures"][0]
    assert f["category"] == "product_defect" and f["severity"] == "high"          # the rules decided
    assert f["ai_suggested_category"] == "test_defect" and f["ai_explanation"]     # the AI only suggests
    assert f["bug"]["expected"] is not None and f["next_action"]


def _state(**kw):
    page = {"url": "https://x.test/", "slug": "home", "status": 200, "title": "Home"}
    base = {"app_map": [page, dict(page, url="https://x.test/about", slug="about")], "log": [],
            "results": [{"nodeid": "a", "test": "test_a", "file": "test_site.py", "outcome": "passed"}],
            "failures": [], "login": {}, "crawl": {"limit_reached": False}, "healing_log": []}
    base.update(kw)
    return base


def test_release_gates_decide_the_verdict():
    from backend.agents.reporter import decide_verdict
    assert decide_verdict(_state())[0] == "Ready"
    assert decide_verdict(_state(app_map=[]))[0] == "Insufficient Evidence"
    assert decide_verdict(_state(results=[]))[0] == "Insufficient Evidence"
    blocker = {"source": "test", "category": "product_defect", "severity": "high", "confidence": "high",
               "explanation": "Empty form was accepted"}
    assert decide_verdict(_state(failures=[blocker]))[0] == "Not Ready"
    unsure = dict(blocker, confidence="low")  # a low-confidence finding is a risk, not a blocker
    assert decide_verdict(_state(failures=[unsure]))[0] == "Ready with Risks"
    assert decide_verdict(_state(crawl={"limit_reached": True, "limit": 3, "not_visited_count": 9}))[0] == "Ready with Risks"
    # the whole app is behind a login and nobody could log in: not enough evidence (was "Not Ready" on OrangeHRM)
    walled = _state(login={"found": True, "logged_in": False, "required": True, "note": "no test account"},
                    app_map=[{"url": "https://x.test/auth/login", "slug": "login", "status": 200}])
    assert decide_verdict(walled)[0] == "Insufficient Evidence"
    # most tests could not give an answer (broken scripts): not enough evidence either
    broken = [{"source": "test", "category": "test_defect", "severity": "low", "explanation": "x"}] * 3
    results = [{"nodeid": str(i), "test": "t", "file": "f", "outcome": "failed"} for i in range(4)]
    assert decide_verdict(_state(failures=broken, results=results))[0] == "Insufficient Evidence"


def test_the_feature_coverage_gate_never_claims_full_coverage_with_gaps():
    from backend.agents.reporter import decide_verdict
    full = {"features": {"discovered": 10, "tested": 8, "verified": 8, "failed": 0, "blocked": 2, "needs_login": 0,
                         "inconclusive": 0, "clicked_only": 0, "skipped": 0, "unresolved": 0},
            "pages": {"not_reached": 0, "sampled_out": 3}}
    verdict, _, gates = decide_verdict(_state(feature_counts=full))
    gate = next(g for g in gates if g["id"] == "feature_coverage")
    assert verdict == "Ready" and gate["status"] == "pass" and "8 verified" in gate["detail"]
    gaps = dict(full, features=dict(full["features"], unresolved=3, clicked_only=1))
    verdict, reasons, gates = decide_verdict(_state(feature_counts=gaps))
    gate = next(g for g in gates if g["id"] == "feature_coverage")
    assert verdict == "Ready with Risks" and gate["status"] == "risk"
    assert gate["detail"].startswith("Not complete") and "3 not tested" in gate["detail"] and gate["detail"] in reasons
    assert all(g["id"] != "feature_coverage" for g in decide_verdict(_state())[2])  # (no registry: no claim either way)


def test_structured_test_cases_have_every_field_and_stable_ids():
    from backend.agents.test_design import builtin_journeys, finalize_cases, small_checks, validate_case
    page = {"url": "https://x.test/", "slug": "home", "title": "Home", "itemNames": [], "inputs": [], "forms": [],
            "buttons": [], "links": [{"href": "https://x.test/a", "text": "A"}, {"href": "https://x.test/b", "text": "B"}]}
    pages = [page, dict(page, url="https://x.test/a", slug="a", links=[]), dict(page, url="https://x.test/b", slug="b", links=[])]
    first = finalize_cases(builtin_journeys(pages) + small_checks(pages, []), {"app_map": pages})
    again = finalize_cases(builtin_journeys(pages) + small_checks(pages, []), {"app_map": pages})
    assert [c["tc_id"] for c in first] == [c["tc_id"] for c in again]           # same site -> same IDs
    assert len({c["tc_id"] for c in first}) == len(first)                      # no duplicates
    for c in first:
        assert validate_case(c) == [], (c["id"], validate_case(c))
    assert validate_case({"title": "x"})  # an incomplete case is reported


def test_ai_test_cases_for_features_the_site_does_not_have_are_left_out(monkeypatch):
    """A small AI model invents a search / cart / checkout for a login + register site: those cases are dropped,
    the ones about what is really there (dropdown, checkbox, forgot password) are kept."""
    import json

    from backend.agents import test_design
    login = {"url": "https://x.test/login", "slug": "login", "title": "Login", "itemNames": [], "forms": [],
             "inputs": [{"type": "email", "selector": "#e"}, {"type": "password", "selector": "#p"}],
             "buttons": [{"text": "Login", "selector": "#go"}],
             "links": [{"href": "https://x.test/register", "text": "Register"},
                       {"href": "https://x.test/forgot", "text": "Forgot password?"}]}
    register = dict(login, url="https://x.test/register", slug="register", links=[],
                    inputs=login["inputs"] + [{"tag": "select", "type": "select-one", "selector": "select"},
                                              {"type": "checkbox", "selector": "input[type=checkbox]"}])
    answer = [{"title": t, "steps": ["Open the page", s], "expected": "ok"} for t, s in [
        ("Verify search functionality", "Type 'phone' in the search box"),
        ("Verify cart functionality", "Click Add to cart"),
        ("Verify checkout process", "Click Checkout"),
        ("Verify dropdown functionality", "Choose an occupation in the dropdown"),
        ("Verify checkbox functionality", "Tick the checkbox"),
        ("Verify password reset process", "Click 'Forgot password?'")]]
    from backend import llm
    monkeypatch.setattr(llm, "ask_llm", lambda *a, **k: json.dumps(answer))  # (the answer is validated in llm)
    kept = [c["title"] for c in test_design.ai_flows([login, register])]
    assert kept == ["Verify dropdown functionality", "Verify checkbox functionality", "Verify password reset process"]


def test_regression_comparison_by_stable_id(tmp_path):
    import json

    from backend.agents.reporter import compare_with_previous
    old = tmp_path / "x.test_20260101_100000"
    old.mkdir()
    (old / "summary.json").write_text(json.dumps({"verdict": "Ready"}))
    (old / "test_cases.json").write_text(json.dumps([
        {"tc_id": "TC-00000001", "title": "a", "execution_status": "Passed"},
        {"tc_id": "TC-00000002", "title": "b", "execution_status": "Failed"},
        {"tc_id": "TC-00000003", "title": "c", "execution_status": "Passed"}]))
    (tmp_path / "x.test_extra_20260101_100000").mkdir()  # another site with a similar name: ignored
    now = tmp_path / "x.test_20260102_100000"
    now.mkdir()
    cases = [{"tc_id": "TC-00000001", "title": "a", "execution_status": "Failed"},
             {"tc_id": "TC-00000002", "title": "b", "execution_status": "Passed"},
             {"tc_id": "TC-00000004", "title": "d", "execution_status": "Passed"}]
    cmp = compare_with_previous({"site_key": "x.test"}, now, cases)
    assert cmp["previous_run"] == old.name
    assert cmp["counts"] == {"newly failing": 1, "fixed": 1, "new test case": 1, "removed": 1}
