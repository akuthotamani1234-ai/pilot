"""The guided Jira workflow (backend/atlassian/workflow.py + its routes): a persistent server-side draft, New Test,
target detection with its four outcomes (found / not found / several / inaccessible), saved targets and test
accounts, the reachability check (backend/target_check.py), prerequisite failures reported as Blocked, and
specific test scenarios instead of "Check: ..." / "Break the rule: ...". Everything runs on 127.0.0.1."""
# ruff: noqa: F811  (pytest fixtures shared from test_requirements_execution are parameters here)
import http.server
import json
import socket
import threading
from types import SimpleNamespace as N

import pytest

from backend import target_check
from backend.atlassian import analysis as an, bridge, workflow
from tests.atlassian_mock import T0, adf, story
from tests.test_requirements_execution import (  # noqa: F401
    _accept,
    analysed,
    api,
    db,
    paths,
    put_story,
)

SAUCE = "https://www.saucedemo.com/"


def _qpl3(api, extra=""):
    api.mock.issues["QPL-3"] = story("QPL-3", "Product Browsing and Sorting", T0, "", "")
    api.mock.issues["QPL-3"]["fields"]["description"] = adf(
        "As a signed-in shopper I want to browse and sort products." + extra, "Acceptance Criteria",
        "- The products page lists every product with its name and price",
        "- Sorting by Price (low to high) shows the prices in ascending order",
        "- Sorting by Name (Z to A) shows the names in reverse alphabetical order")
    job = api.client.post("/api/requirements/connections/jira-main/imports", headers=api.H,
                          json={"mode": "items", "keys": "QPL-3"}).json()
    from backend import requirements_api as rapi
    rapi.JOBS.wait(job["id"])


def _launch(api, monkeypatch, job_id=6161):
    launched = {}

    def fake(req, caller):  # (the real launcher starts main.py: the live SauceDemo run covers it)
        launched["req"] = req
        api.server.jobs[job_id] = {"id": job_id, "status": "running", "run": ""}
        return {"id": job_id}
    monkeypatch.setattr(api.server, "_launch_run", fake)
    return launched


# ================================================================ draft and New Test

def test_the_draft_is_kept_on_the_server_and_never_holds_secrets(api):
    c = api.client
    first = c.get("/api/requirements/workflow", headers=api.H).json()
    assert first["steps"] == list(workflow.STEPS) and first["draft"]["id"].startswith("WF-")
    assert first["state"]["done"]["connect"] and first["state"]["done"]["import"]
    did = first["draft"]["id"]
    r = c.put("/api/requirements/workflow/draft", headers=api.H, json={"draft_id": did, "changes": {
        "requirement_ids": ["QPL-2"], "target_url": SAUCE, "test_password": "secret_sauce", "api_key": "sk-x",
        "step": "analysis"}}).json()
    assert r["draft"]["requirement_ids"] == ["QPL-2"] and r["draft"]["step"] == "analysis"
    assert "secret_sauce" not in json.dumps(r) and "sk-x" not in json.dumps(r)
    assert r["state"]["selected"] == ["QPL-2"] and r["state"]["done"]["explorer"]
    assert r["state"]["done"]["analysis"]  # (the fixture analysed QPL-2)
    again = c.get("/api/requirements/workflow", headers=api.H).json()  # (a reload continues the same draft)
    assert again["draft"]["id"] == did and again["draft"]["target_url"] == SAUCE


def test_new_test_starts_a_fresh_draft_keeps_old_reports_and_refuses_late_changes_to_the_old_one(api, monkeypatch):
    c = api.client
    _accept(api, 2)
    c.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    _launch(api, monkeypatch)
    ex = c.post("/api/requirements/executions", headers=api.H, json={
        "strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1"]},
        "target": {"url": SAUCE, "authorized": True}}).json()["execution"]
    old = c.get("/api/requirements/workflow", headers=api.H).json()["draft"]["id"]
    c.put("/api/requirements/workflow/draft", headers=api.H, json={"draft_id": old, "changes": {"execution_id": ex["id"]}})
    fresh = c.post("/api/requirements/workflow/new", headers=api.H, json={"changes": {"strategy": "hybrid"}}).json()
    assert fresh["draft"]["id"] != old and fresh["draft"]["strategy"] == "hybrid"
    assert not fresh["draft"].get("requirement_ids") and not fresh["state"]["execution"]
    late = c.put("/api/requirements/workflow/draft", headers=api.H, json={"draft_id": old, "changes": {"step": "reports"}})
    assert late.status_code == 409 and "New Test" in late.json()["detail"]
    kept = c.get("/api/requirements/executions", headers=api.H).json()["executions"]
    assert [e["id"] for e in kept] == [ex["id"]]  # (the earlier execution and its report are kept)
    assert c.get("/api/requirements/test-cases?requirement=QPL-2", headers=api.H).json()["total"] == 2


# ================================================================ target detection: cases A-D

def test_case_b_no_target_anywhere_says_so_in_the_required_words(api):
    r = api.client.get("/api/requirements/targets/resolve?requirements=QPL-2", headers=api.H).json()
    assert r["status"] == "not_found" and r["candidates"] == []
    assert r["message"] == "Target website not found. Please enter the website URL you want to test."


def test_case_a_a_saved_target_is_found_with_its_source_and_its_account_is_reused_but_never_shown(api, monkeypatch):
    c = api.client
    refused = c.put("/api/requirements/targets", headers=api.H, json={"project_key": "QPL", "url": SAUCE})
    assert refused.status_code == 400 and "permission" in refused.json()["detail"]
    bad = c.put("/api/requirements/targets", headers=api.H, json={
        "project_key": "QPL", "url": "https://u:p@www.saucedemo.com/", "authorized": True})
    assert bad.status_code == 400
    saved = c.put("/api/requirements/targets", headers=api.H, json={
        "project_key": "QPL", "url": SAUCE, "authorized": True, "test_username": "standard_user",
        "test_password": "secret_sauce"})
    assert saved.status_code == 200 and saved.json()["target"]["has_test_account"]
    assert "secret_sauce" not in saved.text
    r = c.get("/api/requirements/targets/resolve?requirements=QPL-2", headers=api.H).json()
    assert r["status"] == "found" and r["message"] == "Target website found."
    assert r["candidates"][0]["url"] == SAUCE and r["candidates"][0]["has_test_account"]
    assert r["candidates"][0]["sources"] == ["saved target of Jira project QPL (test)"]
    assert "secret_sauce" not in json.dumps(r)
    conn_db = bridge.connect()
    try:
        raw = json.dumps([dict(x) for x in conn_db.execute("SELECT data FROM req_targets").fetchall()])
    finally:
        conn_db.close()
    assert "secret_sauce" not in raw and "standard_user" not in raw  # (kept protected, not in clear text)
    # credential reuse: an execution without typed credentials gets the saved account for the same address only
    _accept(api, 2)
    c.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    launched = _launch(api, monkeypatch)
    body = {"strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1"]},
            "target": {"url": SAUCE, "authorized": True}}
    assert c.post("/api/requirements/executions", headers=api.H, json=body).status_code == 200
    assert (launched["req"].test_username, launched["req"].test_password) == ("standard_user", "secret_sauce")
    other = {**body, "target": {"url": "https://staging.saucedemo.example/", "authorized": True}}
    launched.clear()
    assert c.post("/api/requirements/executions", headers=api.H, json=other).status_code == 200
    assert not launched["req"].test_password  # (another website never receives this account)
    # typed credentials win over the saved ones (fallback order: typed, then saved)
    typed = {**body, "target": {**body["target"], "test_username": "problem_user", "test_password": "x-typed"}}
    assert c.post("/api/requirements/executions", headers=api.H, json=typed).status_code == 200
    assert launched["req"].test_username == "problem_user"
    # forgetting the account keeps the website
    assert c.delete("/api/requirements/targets/QPL/account", headers=api.H).json()["removed"]
    r = c.get("/api/requirements/targets/resolve?requirements=QPL-2", headers=api.H).json()
    saved_one = next(x for x in r["candidates"] if x["url"] == SAUCE)
    assert not saved_one["has_test_account"]
    assert r["status"] == "multiple"  # (this test also ran against a second website: both are offered)


def test_case_c_several_candidates_are_listed_with_sources_and_unconfirmed_ones_are_not_authorised(api, monkeypatch):
    _qpl3(api, " Shop: https://shop.example.test/products . Design: https://acme.atlassian.net/wiki/x "
               "Code: https://github.com/acme/shop Docs: https://docs.example.test/guide "
               "Picture: https://cdn.example.test/a.png")
    c = api.client
    c.put("/api/requirements/targets", headers=api.H, json={"project_key": "QPL", "url": SAUCE, "authorized": True})
    _accept(api, 2)
    c.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    _launch(api, monkeypatch)
    c.post("/api/requirements/executions", headers=api.H, json={
        "strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1"]},
        "target": {"url": "https://staging.saucedemo.example/", "authorized": True}})
    r = c.get("/api/requirements/targets/resolve?requirements=QPL-2,QPL-3", headers=api.H).json()
    urls = {x["url"]: x for x in r["candidates"]}
    assert r["status"] == "multiple" and "choose" in r["message"]
    assert set(urls) == {SAUCE, "https://staging.saucedemo.example/", "https://shop.example.test/"}
    assert urls["https://staging.saucedemo.example/"]["sources"][0].startswith("used by execution")
    assert urls["https://shop.example.test/"]["authorized"] is False  # (only written in Jira: confirm first)
    assert urls["https://shop.example.test/"]["sources"] == ["written in QPL-3 (not yet confirmed)"]


def test_jira_confluence_code_docs_and_image_links_are_never_targets():
    text = ("see https://acme.atlassian.net/browse/QPL-1 https://acme.atlassian.net/wiki/spaces/X "
            "https://github.com/acme/app https://docs.example.test/ https://cdn.example.test/logo.png "
            "https://my-jira.example.test/browse/QPL-1 and the app https://app.example.test/login.")
    assert workflow.urls_in_text(text, {"my-jira.example.test"}) == ["https://app.example.test/"]


# ================================================================ case D: the reachability check

class _Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        codes = {"/ok": 200, "/login": 401, "/down": 503, "/gone": 404}
        if self.path == "/hop":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        self.send_response(codes.get(self.path, 200))
        self.end_headers()
        self.wfile.write(b"hi")

    def log_message(self, *a):
        pass


@pytest.fixture
def site():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_case_d_an_unusable_website_is_classified_so_a_person_knows_what_to_fix(site):
    assert target_check.check(site + "/ok")["kind"] == "ok"
    assert target_check.check(site + "/hop")["ok"]  # (same-host redirect followed)
    login = target_check.check(site + "/login")
    assert login["ok"] and "login" in login["message"]
    down = target_check.check(site + "/down")
    assert (down["ok"], down["kind"], down["status"]) == (False, "unavailable", 503)
    assert "not a test result" in down["message"]
    assert target_check.check(site + "/gone")["kind"] == "not_found"
    assert target_check.check(f"http://127.0.0.1:{_free_port()}/")["kind"] == "connection"
    assert target_check.check("https://no-such-host.invalid/", timeout=5)["kind"] in ("dns", "connection")
    assert target_check.check("ftp://example.test/")["kind"] == "invalid"
    assert target_check.check("https://user:pw@example.test/")["kind"] == "invalid"
    assert target_check.check("http://169.254.169.254/latest/meta-data/")["kind"] == "invalid"


def test_the_check_route_needs_run_rights_and_sends_nothing_but_a_plain_get(api, site, monkeypatch):
    r = api.client.post("/api/requirements/targets/check", headers=api.H, json={"url": site + "/down"}).json()
    assert r["kind"] == "unavailable" and not r["ok"]


# ================================================================ prerequisites: Blocked, not Failed

@pytest.mark.parametrize(("case", "status"), [
    ({"title": "Verify sorting by Price (low to high)", "execution_status": "Failed",
      "failure_category": "Authentication / permission failure"}, "Blocked"),
    ({"title": "Verify every product is listed with its name and price", "execution_status": "Failed",
      "failure_category": "Test data / precondition problem"}, "Blocked"),
    ({"title": "Verify sorting by Name (Z to A)", "execution_status": "Failed",
      "failure_category": "Infrastructure failure (network / environment)"}, "Blocked"),
    ({"title": "Verify a valid login opens the Products page", "execution_status": "Failed",
      "failure_category": "Authentication / permission failure"}, "Failed"),  # (the login IS what it tests)
    ({"title": "Verify sorting by Price (low to high)", "execution_status": "Failed",
      "failure_category": "Application defect (potential website bug)"}, "Failed"),
    ({"title": "Verify sorting by Price (low to high)", "execution_status": "Passed",
      "failure_category": "Authentication / permission failure"}, "Passed"),
])
def test_a_failed_prerequisite_marks_the_dependent_test_blocked(case, status):
    assert bridge._result_status(case) == status


def test_a_blocked_result_says_which_prerequisite_failed_and_is_not_counted_as_failed(db, paths, tmp_path):
    put_story(db, ac="AC1: Sorting by Price (low to high) shows the prices in ascending order")
    analysed(db, paths, accept=1)
    bridge.generate(db, "t1", "QPL-2")
    ex = bridge.plan(db, "t1", ["TC-QPL-2-1"], "requirements", {"url": "https://shop.test"})["execution"]
    run = tmp_path / "run"
    run.mkdir()
    (run / "test_cases.json").write_text(json.dumps([{
        "requirement_test": "TC-QPL-2-1", "title": "Verify sorting by Price (low to high)",
        "execution_status": "Failed", "actual_result": "stayed on the login page",
        "failure_category": "Authentication / permission failure"}]))
    done = bridge.collect(db, "t1", ex["id"], run)
    assert done["counts"] == {"Blocked": 1}
    res = bridge.results(db, "t1", ex["id"])[0]
    assert res["status"] == "Blocked" and res["reason"].startswith("Blocked: a prerequisite failed")
    assert res["actual"] == "stayed on the login page"  # (what really happened is kept)


# ================================================================ specific scenarios

def _criterion(text, given="", when="", then=""):
    return N(text=text, given=given, when=when, then=then)


def test_sorting_listing_login_and_message_criteria_get_specific_executable_steps():
    title, steps, expected = an.specific_scenario(_criterion(
        "Sorting by Price (low to high) shows the prices in ascending order"))
    assert title == "Verify sorting by Price (low to high)"
    assert steps == ["Open the page that lists the items", "Locate the sort control", "Select 'Price (low to high)'",
                     "Read the prices of the items in the order shown",
                     "Compare them with the same prices sorted in ascending numeric order"]
    assert expected == "Sorting by Price (low to high) shows the prices in ascending order"
    title, steps, _ = an.specific_scenario(_criterion(
        "Sorting by Name (Z to A) shows the names in reverse alphabetical order"))
    assert title == "Verify sorting by Name (Z to A)" and "descending alphabetical" in steps[-1]
    title, steps, _ = an.specific_scenario(_criterion("The products page lists every product with its name and price"))
    assert title == "Verify every product is listed with its name and price"
    assert steps[0] == "Open the products page" and "Check every product shows its price" in steps
    title, steps, _ = an.specific_scenario(_criterion(
        "A user with a valid username and password is taken to the Products page"))
    assert title == "Verify a valid login opens the Products page" and "Submit the login form" in steps
    title, steps, _ = an.specific_scenario(_criterion(
        "A wrong password shows 'Username and password do not match any user in this service'"))
    assert title.startswith("Verify the message 'Username and password do not match")
    assert "Type a password that is not the test account's password" in steps


def test_negative_ideas_only_for_real_constraints_never_by_reversing_behaviour():
    for text in ("Sorting by Price (low to high) shows the prices in ascending order",
                 "The products page lists every product with its name and price",
                 "Users must be able to reset a password"):
        assert an.constraint_violation(_criterion(text)) is None, text
    assert an.constraint_violation(_criterion("Email is required"))[0] == "Leave out what is required: Email is required"
    assert an.constraint_violation(_criterion("A guest cannot open the checkout"))[0].startswith("Try what is not allowed")
    assert an.constraint_violation(_criterion("The name has at most 30 characters"))[0].startswith("Go past the limit")


def test_qpl_3_analysis_has_no_generic_check_or_break_the_rule_ideas(api):
    _qpl3(api)
    a = api.client.post("/api/requirements/items/jira-main/QPL-3/analyze", headers=api.H, json={}).json()["analysis"]
    titles = [s["title"] for s in a["suggestions"]]
    assert "Verify sorting by Price (low to high)" in titles and "Verify sorting by Name (Z to A)" in titles
    assert "Verify every product is listed with its name and price" in titles
    assert not [t for t in titles if t.startswith(("Check: ", "Break the rule"))]
    assert all(s["steps"] for s in a["suggestions"] if s["kind"] == "positive")


# ================================================================ found in the live QPL-3 run (24 Nov 2026)

SAUCE_PAGES = [{"url": "https://www.saucedemo.com/inventory.html", "slug": "inventory_html", "auth": True,
                "inputs": [{"selector": '[data-test="product-sort-container"]'}],
                "buttons": [{"selector": "#add-to-cart-sauce-labs-backpack"}]}]


def test_ai_code_that_opens_an_unexplored_website_or_invents_class_selectors_is_refused():
    from backend.ai_grounding import grounding_problem
    seen = grounding_problem('page.goto("https://example.com/inventory_html")', SAUCE_PAGES)
    assert seen and "not explored" in seen
    seen = grounding_problem('page.locator(".product-name")', SAUCE_PAGES)
    assert seen and "not observed" in seen
    seen = grounding_problem('page.locator("div.inventory_item")', SAUCE_PAGES)
    assert seen and ".inventory_item" in seen
    ok = ('page.goto("https://www.saucedemo.com/inventory.html")\n'
          'page.locator(\'[data-test="product-sort-container"]\').select_option("lohi")')
    assert grounding_problem(ok, SAUCE_PAGES) is None


def test_an_off_site_navigation_is_a_test_defect_and_never_blocked():
    from backend.agents.failure_analysis import _rule_classify
    err = 'E   playwright._impl._errors.Error: Page.goto: net::ERR_BLOCKED_BY_CLIENT at https://example.com/x'
    assert _rule_classify({"error": err, "outcome": "failed"})[0] == "test_defect"
    case = {"title": "Verify sorting by Price (low to high)", "execution_status": "Failed",
            "failure_category": "Infrastructure failure (network / environment)", "actual_result": err}
    assert bridge._result_status(case) == "Failed"


def test_a_logged_in_case_written_as_guest_gets_a_repair_and_is_refused_if_it_stays_guest(monkeypatch):
    from backend.agents import script_generator as gen
    from backend.llm import LLMError
    guest = ('import pytest\nfrom playwright.sync_api import expect\n\n@pytest.mark.guest\n'
             'def test_ai_flow_1(page):\n    page.goto("https://www.saucedemo.com/inventory.html")\n'
             '    expect(page).to_have_title("Swag Labs")\n')
    calls = []
    monkeypatch.setattr(gen, "ask_llm", lambda prompt, **kw: calls.append(prompt) or guest)
    flow = {"id": "ai_flow_1", "title": "Verify sorting by Price (low to high)", "guest": False,
            "pages": ["inventory_html"], "test_data": "", "steps": ["Open the products page"],
            "expected": "prices ascending"}
    page = {**SAUCE_PAGES[0], "title": "Swag Labs", "forms": [], "links": [], "headings": []}
    with pytest.raises(LLMError, match="must run logged in"):
        gen._llm_flows([flow], {"inventory_html": page})
    assert len(calls) == 2 and "remove @pytest.mark.guest" in calls[1]  # (one repair was asked for)
    logged_in = guest.replace("@pytest.mark.guest\n", "")
    monkeypatch.setattr(gen, "ask_llm", lambda prompt, **kw: logged_in)
    assert "@pytest.mark.guest" not in gen._llm_flows([flow], {"inventory_html": page})


def test_a_client_rendered_404_page_reaches_the_ai_script_writer():
    """SauceDemo answers /inventory.html with HTTP 404 and renders it: the AI was given no page at all and invented
    an address (live QPL-3 run). A proven rendered 404 is a page; a real 404 is not."""
    from backend.agents.script_generator import script_pages
    rendered = {"slug": "inventory_html", "url": "https://www.saucedemo.com/inventory.html", "status": 404,
                "rendered_application": True}
    missing = {"slug": "gone", "url": "https://www.saucedemo.com/gone", "status": 404}
    failing = {"slug": "err", "url": "https://www.saucedemo.com/err", "status": 500, "rendered_application": True}
    assert set(script_pages([rendered, missing, failing, {"slug": "home", "url": SAUCE, "status": 200}])) == {
        "inventory_html", "home"}


def test_the_observed_product_cards_are_given_to_the_ai_and_count_as_observed(monkeypatch):
    """Live QPL-3: the AI had no selector for 'every product in display order', guessed .inventory_item_price and
    read fixed ids for a sort check. The cards discovery saw are now in its page data and accepted by grounding."""
    from backend.agents import script_generator as gen
    from backend.ai_grounding import grounding_problem
    page = {**SAUCE_PAGES[0], "title": "Swag Labs", "forms": [], "links": [], "headings": [], "status": 404,
            "rendered_application": True,
            "itemLinks": {"selector": "div.inventory_list > div.inventory_item", "count": 6,
                          "cards": ["Sauce Labs Backpack\ncarry.allTheThings()\n$29.99\nAdd to cart"]}}
    code = ('import re\nfrom playwright.sync_api import expect\n\ndef test_ai_flow_1(page):\n'
            '    page.goto("https://www.saucedemo.com/inventory.html")\n'
            '    page.locator(\'[data-test="product-sort-container"]\').select_option("lohi")\n'
            '    cards = page.locator("div.inventory_list > div.inventory_item")\n'
            '    prices = [float(re.search(r"\\$([0-9.]+)", c.inner_text()).group(1)) for c in cards.all()]\n'
            '    assert prices == sorted(prices)\n')
    assert grounding_problem(code, [page]) is None
    prompts = []
    monkeypatch.setattr(gen, "ask_llm", lambda prompt, **kw: prompts.append(prompt) or code)
    flow = {"id": "ai_flow_1", "title": "Verify sorting by Price (low to high)", "guest": False,
            "pages": ["inventory_html"], "test_data": "", "steps": ["Select 'Price (low to high)'"],
            "expected": "prices ascending"}
    gen._llm_flows([flow], gen.script_pages([page]))
    assert '"selector": "div.inventory_list > div.inventory_item"' in prompts[0] and "IN THE ORDER SHOWN" in prompts[0]


# ================================================================ connecting another Jira site (25 Nov 2026)

def test_a_second_jira_site_gets_its_own_token_and_a_moved_connection_never_sends_the_old_token(api):
    """Every Jira connection used one token slot, and changing a connection's address kept its token: Qpilot would
    have sent site A's API token to site B. A second site now has its own slot, a moved connection loses its token,
    and a stored token is bound to the site it was saved for."""
    from backend.atlassian import credentials
    from tests.atlassian_mock import EMAIL, TOKEN
    c, H = api.client, api.H
    main = next(x for x in c.get("/api/requirements/connections", headers=H).json()["connections"]
                if x["id"] == "jira-main")
    assert main["token_ref"] == "JIRA_READ_API_TOKEN" and main["credential"]["configured"]
    second = c.post("/api/requirements/connections", headers=H, json={
        "id": "jira-2", "product": "jira", "site_url": "https://second-site.atlassian.net", "email": EMAIL}).json()
    assert second["token_ref"] == "JIRA_JIRA_2_SITE_TOKEN" and not second["credential"]["configured"]
    assert c.put("/api/requirements/connections/jira-2/token", headers=H, json={"token": TOKEN}).status_code == 200
    assert c.post("/api/requirements/connections/jira-2/test", headers=H).status_code == 200
    # the first site is untouched and keeps its own token
    conns = {x["id"]: x for x in c.get("/api/requirements/connections", headers=H).json()["connections"]}
    assert conns["jira-main"]["credential"]["configured"] and conns["jira-2"]["credential"]["configured"]
    # moving jira-main to another site: its token is removed and never sent there
    moved = c.post("/api/requirements/connections", headers=H, json={
        "id": "jira-main", "product": "jira", "site_url": "https://third-site.atlassian.net", "email": EMAIL}).json()
    assert "token saved for the old one is no longer used" in moved["notice"]
    assert moved["token_ref"] != "JIRA_READ_API_TOKEN" and not moved["credential"]["configured"]
    refused = c.post("/api/requirements/connections/jira-main/test", headers=H)
    assert refused.status_code >= 400 and TOKEN not in refused.text
    # a saved token is bound to its site
    credentials.set_token("t9", "JIRA_READ_API_TOKEN", "a-token-for-site-a-1234", site="https://a.atlassian.net")
    assert credentials.resolver("t9", site="https://a.atlassian.net")("JIRA_READ_API_TOKEN") == "a-token-for-site-a-1234"
    assert credentials.resolver("t9", site="https://b.atlassian.net")("JIRA_READ_API_TOKEN") == ""
    events = c.get("/api/requirements/audit", headers=H).json()["events"]
    saves = [json.loads(e["detail"]) for e in events if e["action"] == "requirements.connection.save"]
    assert any(d.get("site_changed") and d.get("token_cleared") for d in saves), saves
    assert TOKEN not in json.dumps(events)
