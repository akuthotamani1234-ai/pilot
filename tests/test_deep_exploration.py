"""Deep testing behind a login (tests/demo_store.py, real hidden Chromium):
the explorer logs in FIRST (via the "Sign in" link, two-step login), explores the pages behind the login before
public ones, goes deeper than 3 clicks from the start, visits every discovered /product/{id} route, records /admin as needing other
permissions, inspects every page (type + features) and never uses a protected action."""
import json

import pytest

from backend.config import settings
from tests.demo_store import EMAIL, PASSWORD, PRODUCTS, DemoStore


@pytest.fixture(scope="module")
def store():
    s = DemoStore().start()
    yield s
    s.stop()


@pytest.fixture(scope="module")
def explored(store, tmp_path_factory):  # (one crawl for all the checks below)
    from backend.agents.discovery import discovery_agent
    run = tmp_path_factory.mktemp("deep")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "test_username", EMAIL)
        mp.setattr(settings, "test_password", PASSWORD)
        mp.setattr(settings, "headless", True)
        mp.setattr(settings, "max_pages", 100)
        mp.setattr(settings, "max_depth", 0)
        mp.setattr(settings, "pattern_samples", 0)
        mp.setenv("TEST_USERNAME", EMAIL)
        mp.setenv("TEST_PASSWORD", PASSWORD)
        store.visited.clear()
        out = discovery_agent({"url": store.url, "run_dir": str(run), "site_key": "store", "log": []})
        yield out, run, store


def _path(url, store):
    return url.replace(store.url, "") or "/"


def test_logs_in_first_and_explores_the_app_behind_it(explored):
    out, run, store = explored
    login = out["login"]
    assert login["outcome"] == "success" and _path(login["page"], store) == "/signin"  # found via the Sign-in link
    assert any("password box is gone" in e for e in login["evidence"])
    order = [(_path(p["url"], store), bool(p.get("auth"))) for p in out["app_map"]]
    auth = [u for u, a in order if a]
    assert len(auth) >= 12, auth
    # the app first: every page behind the login was visited before the public "About" page
    assert [u for u, _ in order].index("/about") > max(i for i, (_, a) in enumerate(order) if a)
    # deeper than 3 clicks from the start (start -> sign in -> dashboard -> orders -> order -> tracking)
    assert any(u.endswith("/tracking") for u in auth)
    for must in ("/dashboard", "/shop", "/cart", "/wishlist", "/orders", "/account", "/addresses"):
        assert must in auth, must


def test_inspects_every_page_and_records_what_was_not_tested(explored):
    out, run, store = explored
    by_path = {_path(p["url"], store): p for p in out["app_map"]}
    shop = by_path["/shop"]
    assert shop["page_type"] == "listing"
    assert {"search", "suggestions", "items", "filter", "sort", "pagination"} <= set(shop["features"]), shop["features"]
    product = next(p for u, p in by_path.items() if u.startswith("/product/"))
    assert product["page_type"] == "product"
    assert {"add_to_cart", "wishlist", "option", "protected"} <= set(product["features"]), product["features"]
    assert by_path["/orders"]["page_type"] == "orders" and "order_link" in by_path["/orders"]["features"]
    crawl = json.loads((run / "crawl.json").read_text(encoding="utf-8"))
    assert [_path(x["url"], store) for x in crawl["needs_permission"]] == ["/admin"]
    # ... and only that: its own 403 is not ALSO a console error / failed request (was: 2 false findings)
    assert not [i for i in out["crawl_issues"] if _path(i["url"], store) == "/admin"], out["crawl_issues"]
    product_paths = {u for u in by_path if u.startswith("/product/")}
    assert product_paths == {f"/product/{product['id']}" for product in PRODUCTS}
    assert crawl["sampled"] == 0
    assert not any("same address pattern" in item["reason"] or "same page design" in item["reason"]
                   for item in crawl["skipped"])
    # exploring never used a protected action (it may use reversible test-account ones - add to cart / wishlist -
    # on this test environment, to learn what they do: tests/test_observe.py)
    for never in ("POST /order", "GET /buy", "GET /logout", "POST /cart/remove", "POST /account"):
        assert never not in store.visited, never


def test_feature_and_blocked_cases_are_designed_per_page(explored):
    out, run, store = explored
    from backend.agents.test_design import blocked_cases, builtin_journeys, site_feature_cases
    pages = [p for p in out["app_map"] if not p.get("error") and (p.get("status") or 0) < 400]
    kinds = {c["feature_kind"] for c in site_feature_cases(pages)}
    assert {"filter", "sort", "pagination", "wishlist", "search"} <= kinds
    blocked = {c["title"].split("'")[1] for c in blocked_cases(pages)}
    assert {"Buy now", "Remove", "Place order"} & blocked and "Add to cart" not in blocked
    journeys = {j["journey"] for j in builtin_journeys(pages, limit=100)}
    assert {"product", "orders"} <= journeys
