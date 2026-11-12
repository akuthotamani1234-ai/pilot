"""The feature registry (backend/registry.py): stable ids, pages grouped by address pattern, features linked to their
test cases, and statuses that never count a click - or a discovery - as proof that a feature works."""
from backend import registry


def _page(url, slug, **kw):
    base = {"url": url, "slug": slug, "auth": True, "status": 200, "page_type": "content", "buttons": [], "inputs": [],
            "forms": [], "links": [], "itemNames": [], "behaviour": []}
    return dict(base, **kw)


MENU = {"text": "Categories", "accname": "Categories", "selector": "#menu", "role": "button"}
APP = [
    _page("https://x.test/shop", "shop", page_type="listing", buttons=[MENU],
          inputs=[{"tag": "select", "type": "select-one", "selector": "#sort", "label": "Sort by", "name": "sort",
                   "options": [{"value": "a"}, {"value": "b"}], "accname": "Sort by", "role": "combobox"},
                  {"tag": "input", "type": "search", "selector": "#q", "placeholder": "Search", "name": "q",
                   "accname": "Search", "role": "searchbox"}]),
    _page("https://x.test/product/1", "product_1", page_type="product",
          buttons=[MENU, {"text": "Add to cart", "accname": "Add to cart", "selector": "#add", "role": "button"},
                   {"text": "Buy now", "accname": "Buy now", "selector": "#buy", "role": "button"},
                   {"text": "Next tip", "accname": "Next tip", "selector": "#tip", "role": "button",
                    "revealed_by": "#help", "revealed_by_name": "Open help"}],
          behaviour=[{"control": "Add to cart", "selector": "#add", "effect": "message", "tone": "ok",
                      "message": "Added to your cart"}]),
    _page("https://x.test/product/2", "product_2", page_type="product", buttons=[MENU]),
]
CRAWL = {"skipped": [{"url": "https://x.test/product/9", "reason": "more than 3 pages with the same address "
                                                                  "pattern (/product/{id}) - a sample was tested"}]}


def test_ids_are_stable_and_patterns_and_shared_controls_count_once():
    a, b = registry.build(APP, CRAWL), registry.build(APP, CRAWL)
    assert set(a["features"]) == set(b["features"]) and set(a["pages"]) == set(b["pages"])  # same site -> same ids
    patterns = sorted(pg["pattern"] for pg in a["pages"].values())
    assert patterns == ["/product/{id}", "/shop"]  # /product/1 and /product/2: ONE page pattern with 2 samples
    product = next(pg for pg in a["pages"].values() if pg["pattern"] == "/product/{id}")
    assert product["urls"] == ["https://x.test/product/1", "https://x.test/product/2"] and product["sampled_out"] == 1
    menus = [f for f in a["features"].values() if f["name"] == "Categories"]
    assert len(menus) == 1 and menus[0]["page"] == "site"  # on every page: one shared control, not three
    add = next(f for f in a["features"].values() if f["name"] == "Add to cart")
    assert add["evidence"]["message"] == "Added to your cart"  # what exploring learned is kept as evidence
    tip = next(f for f in a["features"].values() if f["name"] == "Next tip")
    assert tip["revealed_by"] == "Open help"
    assert all(f["status"] in ("inspected", "blocked") for f in a["features"].values())  # nothing tested yet


def test_tests_are_linked_and_only_a_checked_result_verifies():
    reg = registry.build(APP, CRAWL)
    # (the dropdown CONTROL: the "every option can be chosen" step tests it; the sort FEATURE has its own test)
    sort_fid = next(f["id"] for f in reg["features"].values() if f["name"] == "Sort by" and f["level"] == "control")
    add_fid = next(f["id"] for f in reg["features"].values() if f["name"] == "Add to cart")
    menu_fid = next(f["id"] for f in reg["features"].values() if f["name"] == "Categories")
    cases = [
        {"tc_id": "TC-1", "title": "End-to-end on Shop", "pages": ["shop"],
         "parts": [{"page": "shop", "step": {"id": "dropdown_sort_by", "kind": "dropdown", "selector": "#sort"}},
                   {"page": "shop", "step": {"id": "buttons_click", "title": "Every button can be clicked"}}],
         "execution_status": "Passed"},
        {"tc_id": "TC-2", "title": "'Add to cart' shows its message", "pages": ["product_1"], "feature_ids": [add_fid],
         "execution_status": "Failed", "actual_result": "no message appeared"},
        {"tc_id": "TC-3", "title": "'Buy now' on Product - not run (protected action)", "pages": ["product_1"],
         "blocked": True, "execution_status": "Blocked"},
    ]
    registry.link_tests(reg, cases)
    assert {t["tc_id"] for t in reg["features"][sort_fid]["tests"]} == {"TC-1"}
    assert reg["features"][menu_fid]["tests"] == [{"tc_id": "TC-1", "how": "clicks"}]
    registry.record_outcomes(reg, cases)
    f = reg["features"]
    assert f[sort_fid]["status"] == "verified"
    assert f[menu_fid]["status"] == "clicked_only"  # clicked inside a passing case: still NOT verified
    assert f[add_fid]["status"] == "failed" and "no message" in f[add_fid]["why"]
    buy = next(x for x in f.values() if x["name"] == "Buy now")
    assert buy["status"] == "blocked"
    c = reg["counts"]
    assert c["features"]["discovered"] == len(f)
    assert c["features"]["verified"] == sum(1 for x in f.values() if x["status"] == "verified")
    assert c["features"]["unresolved"] == sum(1 for x in f.values() if x["status"] == "unresolved")
    assert all(x["why"] for x in f.values() if x["status"] == "unresolved")  # every gap says why


def test_a_failing_journey_fails_its_workflow_never_the_features_it_went_through():
    """One failing step of a journey (a wrong cart total) fails the JOURNEY - every feature on the way keeps the
    result of its own test: 'Add to cart' has a passing check of its own (verified); the search, only used by the
    failing journey, is not known (inconclusive, with the journey's failure as the reason) - never 'failed'."""
    reg = registry.build(APP, CRAWL)
    add = next(f["id"] for f in reg["features"].values() if f["kind"] == "add_to_cart" and f["level"] == "feature")
    search = next(f["id"] for f in reg["features"].values() if f["kind"] == "search" and f["level"] == "feature")
    cases = [{"tc_id": "TC-J", "title": "Shop: search -> add to cart -> the cart", "journey": "shop", "pages": ["shop"],
              "execution_status": "Failed", "actual_result": "One more should add 20 to the cart total, it went 20 -> 20"},
             {"tc_id": "TC-P", "title": "Shopping journey", "journey": "product", "pages": ["product_1"],
              "execution_status": "Failed", "actual_result": "the cart total did not follow the quantity"},
             {"tc_id": "TC-A", "title": "'Add to cart' adds the item", "pages": ["product_1"],
              "parts": [{"page": "product_1", "step": {"id": "add_to_cart"}}], "execution_status": "Passed"}]
    registry.link_tests(reg, cases)
    assert {"tc_id": "TC-P", "how": "uses"} in reg["features"][add]["tests"]
    registry.record_outcomes(reg, cases)
    f = reg["features"]
    assert f[add]["status"] == "verified"  # its own check passed; the failing journey only USED it
    assert f[search]["status"] == "inconclusive" and "journey" in f[search]["why"] and "cart total" in f[search]["why"]
    workflows = {x["name"]: x["status"] for x in f.values() if x["level"] == "workflow"}
    assert workflows == {"Shop: search -> add to cart -> the cart": "failed", "Shopping journey": "failed"}


def test_a_control_that_showed_nothing_while_exploring_is_inconclusive_not_tested():
    app = [_page("https://x.test/", "home", buttons=[{"text": "Next", "accname": "Next", "selector": "a.slide-next",
                                                      "role": "button", "kind": "slide"}],
                 behaviour=[{"control": "Next", "selector": "a.slide-next", "effect": "nothing", "tone": ""}])]
    reg = registry.build(app, {})
    registry.link_tests(reg, [])
    registry.record_outcomes(reg, [])
    nxt = next(f for f in reg["features"].values() if f["name"] == "Next")
    assert nxt["status"] == "inconclusive" and "nothing visible" in nxt["why"]
    assert reg["counts"]["features"]["tested"] == 0  # tried while exploring is not a test


def test_a_visitor_asked_to_sign_in_needs_a_test_account():
    reg = registry.build(APP, CRAWL)
    add_fid = next(f["id"] for f in reg["features"].values() if f["name"] == "Add to cart")
    cases = [{"tc_id": "TC-9", "title": "x", "pages": ["product_1"], "feature_ids": [add_fid],
              "execution_status": "Skipped", "actual_result": "Skipped: needs a test account (please sign in)"}]
    registry.link_tests(reg, cases)
    registry.record_outcomes(reg, cases)
    assert reg["features"][add_fid]["status"] == "needs_login"
