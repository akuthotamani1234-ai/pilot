"""The whole agent (main.py) on ClassicShop - an older template shop built like the one of the AutomationTestStore
run - first clean and WITHOUT a test account, then with its 3 planted bugs and WITH the test account. Proves the
accuracy fixes end to end (each run takes a few minutes):
  * every page of a shop that picks its pages with ?rt=<route> is visited (the cart, contact and site map were
    skipped as 'the same address pattern' before), and the registry has one page pattern per route;
  * every feature has its own focused test case with its own result - no 'N of M steps failed' bundles;
  * a planted bug fails ITS feature's tests, and every unrelated feature keeps its own (passed) result;
  * search and sorting read the product cards, never the header menu;
  * the report's totals reconcile (metrics.json) and the headline pass rate counts functional test cases only;
  * the shopping journey passes only when every step was verified, and fails on the wrong cart total;
  * protected actions are blocked and never requested; without a test account the pages behind the login are
    reported as not tested; with it, the login is verified and those pages are tested.
"""
import json
import re

import pytest

from tests.accuracy_benchmark import run_agent
from tests.classic_shop import EMAIL, PASSWORD, ClassicShop

pytestmark = pytest.mark.slow  # (runs the whole tester: quick checks leave it out with -m "not slow")


def _load(run):
    def read(name):
        return json.loads((run / name).read_text(encoding="utf-8"))
    return {k: read(f"{k}.json") for k in ("app_map", "test_cases", "results", "registry", "summary", "metrics",
                                            "crawl", "login", "failures")}


@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    shop = ClassicShop().start()
    try:
        run, out = run_agent(shop, tmp_path_factory.mktemp("classic_clean"), account=())
        yield _load(run), shop, run
    finally:
        shop.stop()


@pytest.fixture(scope="module")
def buggy(tmp_path_factory):
    shop = ClassicShop(bugs=True).start()
    try:
        run, out = run_agent(shop, tmp_path_factory.mktemp("classic_bugs"), account=(EMAIL, PASSWORD))
        yield _load(run), shop, run
    finally:
        shop.stop()


def _route(url):
    m = re.search(r"[?&]rt=([^&#]+)", url or "")
    return m.group(1) if m else "index/home"


def _status(d, rx):
    """{title: status} of the test cases whose title matches rx."""
    return {c["title"]: c["execution_status"] for c in d["test_cases"] if re.search(rx, c["title"], re.I)}


def test_every_route_is_visited_and_is_its_own_page_pattern(clean):
    d, shop, run = clean
    routes = {_route(p["url"]) for p in d["app_map"] if not p.get("error")}
    for must in ("index/home", "product/category", "product/special", "product/search", "product/product",
                 "checkout/cart", "account/login", "account/create", "account/invoice", "content/contact",
                 "content/content", "content/sitemap"):
        assert must in routes, (must, sorted(routes))
    patterns = [pg["pattern"] for pg in d["registry"]["pages"].values()]
    assert len(patterns) >= 11 and any("checkout/cart" in p for p in patterns), patterns
    types = {_route(p["url"]): p["page_type"] for p in d["app_map"]}
    assert types["product/product"] == "product" and types["checkout/cart"] == "cart"


def test_each_feature_has_its_own_focused_test_case(clean):
    d, shop, run = clean
    cases = d["test_cases"]
    assert not [c for c in cases if c.get("kind") == "flow" and not c.get("ai")]  # no bundles of unrelated steps
    ids = [c["tc_id"] for c in cases]
    assert len(ids) == len(set(ids))
    by_nodeid = {}
    for r in d["results"]:
        by_nodeid.setdefault((r["file"], r["test"].split("[")[0]), []).append(r)
    for c in [c for c in cases if c.get("kind") == "check"]:
        assert len(c["tests"]) == 1 and c["feature"] and c["feature_ids"], c["title"]
        assert c["preconditions"] and c["steps"] and c["expected"], c["title"]
        if c["execution_status"] == "Passed":  # a pass means its assertions ran
            assert all(r["checks"] > 0 for r in by_nodeid[(c["files"][0], c["tests"][0])]), c["title"]
    assert not any("steps failed" in (r.get("error") or "") for r in d["results"])


def _questions(d):
    """Cases that ask a person (a rule between fields not kept, a control that did nothing): not a claimed bug."""
    return {f.get("tc_id") for f in d["failures"] if f.get("category") in ("rule_violation", "suspect")}


def test_a_clean_shop_gives_no_false_failures(clean):
    d, shop, run = clean
    failed = {c["title"]: c["actual_result"] for c in d["test_cases"] if c["execution_status"] in ("Failed", "Flaky")
              and c["tc_id"] not in _questions(d)}
    assert not failed, failed
    # the e-mail box of type "text" (newsletter, 'Check your order'): no client-side check is not a website bug
    data = [r for r in d["results"] if "email" in r["test"] and r["file"].endswith("_data.py")]
    assert data and not [r for r in data if r["outcome"] == "failed"]
    assert any(r["outcome"] == "inconclusive" for r in data)
    assert not [r for r in d["results"] if r["test"].startswith("test_section_link")
                and re.search(r"review|producttag|description", r["test"])]  # tab links are tabs


def test_search_and_sorting_read_the_product_cards(clean):
    d, shop, run = clean
    search = _status(d, r"^search finds '")
    assert search and set(search.values()) == {"Passed"}, search
    word = re.search(r"'([^']+)'", next(iter(search))).group(1)
    assert word.lower() not in ("home", "welcome", "search", "login")  # a word of a real product name
    sort = _status(d, r"^sorting with")
    assert sort and set(sort.values()) == {"Passed"}, sort
    code = (run / "generated_tests" / "test_features.py").read_text(encoding="utf-8")
    assert "body." not in re.search(r"F = \{[^}]*'items': '([^']*)'", code).group(1)


def test_the_report_totals_reconcile(clean):
    d, shop, run = clean
    m = d["metrics"]
    assert m["consistent"], [c for c in m["consistency"] if not c["ok"]]
    s = d["summary"]
    assert s["pass_rate"] == m["headline"]["percent"] and s["metrics"]["headline"]["name"] == "Functional test cases passed"
    assert s["tests"] == m["single_tests"]["total"] == len(d["results"])
    assert s["test_cases"] == m["test_cases"]["planned"] == len(d["test_cases"])
    g = m["single_tests"]["groups"]
    assert g["links"]["total"] > 0 and sum(x["total"] for x in g.values()) == len(d["results"])
    html = (run / "report.html").read_text(encoding="utf-8")
    assert "Functional test cases passed" in html and "Consistency checks" in html


def test_the_shopping_journey_passes_only_with_every_step_verified(clean):
    d, shop, run = clean
    journey = next(c for c in d["test_cases"] if c.get("journey") == "product")
    assert journey["execution_status"] == "Passed", journey["actual_result"]
    wf = next(w for w in d["metrics"]["workflows"]["list"] if w["tc_id"] == journey["tc_id"])
    done = " | ".join(wf["steps_verified"])
    for step in ("found in the results", "opened", "added", "in the cart", "quantity", "total"):
        assert step in done, (step, wf["steps_verified"])


def test_protected_actions_are_blocked_and_the_missing_account_is_reported(clean):
    d, shop, run = clean
    blocked = {c["title"].split("'")[1] for c in d["test_cases"] if c["execution_status"] == "Blocked"}
    assert "Subscribe" in blocked and blocked & {"Confirm Order", "Checkout"}, blocked
    for never in ("POST checkout/confirm", "GET account/logout", "POST account/subscriber", "POST content/contact",
                  "POST account/create"):
        assert never not in shop.visited, never
    gate = next(g for g in d["summary"]["gates"] if g["id"] == "login")
    assert gate["status"] in ("risk", "missing") and "no test account" in gate["detail"]
    assert not d["summary"]["authenticated"]
    # the pages a visitor is sent away from are listed as not tested - needs a test account (never as tested)
    assert any("account/account" in x["url"] for x in d["crawl"]["needs_login"]), d["crawl"]["needs_login"]
    assert any("needs a test account" in x["why"] for x in d["metrics"]["pages"]["untested"])


def test_a_planted_bug_fails_its_own_feature_and_nothing_else(clean, buggy):
    d, shop, run = buggy
    clean_status = {c["tc_id"]: c["execution_status"] for c in clean[0]["test_cases"]}
    failed = {c["tc_id"]: c for c in d["test_cases"] if c["execution_status"] in ("Failed", "Flaky")
              and c["tc_id"] not in _questions(d)}
    bug_words = re.compile(r"search|doesn't exist|sort|shopping journey|cart", re.I)
    unrelated = [c["title"] for c in failed.values() if not bug_words.search(c["title"])]
    assert not unrelated, unrelated  # e.g. the option, quantity, tabs, menus, login: still passed
    assert any(re.search(r"^search finds", c["title"], re.I) for c in failed.values())
    assert any(re.search(r"doesn't exist", c["title"], re.I) for c in failed.values())
    sort = next(c for c in failed.values() if c["title"].lower().startswith("sorting with"))
    assert "should sort by price" in sort["actual_result"] and "login or register" not in sort["actual_result"].lower()
    journey = next(c for c in d["test_cases"] if c.get("journey") == "product")
    assert journey["execution_status"] == "Failed" and "total" in journey["actual_result"].lower()
    # every case that passed on the clean shop and has nothing to do with the 3 bugs passed again
    same = [c for c in d["test_cases"] if clean_status.get(c["tc_id"]) == "Passed" and not bug_words.search(c["title"])]
    assert same and all(c["execution_status"] == "Passed" for c in same), \
        [c["title"] for c in same if c["execution_status"] != "Passed"]
    # the registry: the broken features failed, the others are verified
    feats = d["registry"]["features"].values()
    assert any(f["kind"] == "sort" and f["status"] == "failed" for f in feats)
    for kind in ("option", "add_to_cart", "login"):
        mine = [f for f in feats if f["kind"] == kind and f["level"] == "feature"]
        assert mine and not [f for f in mine if f["status"] == "failed"], (kind, [f["why"] for f in mine])
    assert d["metrics"]["consistent"], [c for c in d["metrics"]["consistency"] if not c["ok"]]


def test_with_the_test_account_the_login_is_verified_and_its_pages_are_tested(buggy):
    d, shop, run = buggy
    assert d["login"]["logged_in"] and d["login"]["outcome"] == "success"
    auth = {_route(p["url"]) for p in d["app_map"] if p.get("auth")}
    assert {"account/account", "account/history"} <= auth, auth
    assert d["summary"]["authenticated"] and d["summary"]["authenticated_pages"] >= 2
    assert next(g for g in d["summary"]["gates"] if g["id"] == "login")["status"] == "pass"
