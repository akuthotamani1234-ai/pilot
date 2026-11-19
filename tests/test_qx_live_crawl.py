"""The crawl uses the Qpilot X rules while it walks, not only when the run ends."""
import json

from playwright.sync_api import sync_playwright

from backend.agents.discovery import (
    EXTRACT_JS,
    _Frontier,
    click_actions_allowed,
    click_page,
    pending_visit,
    place_link,
    resume_seen,
    store_api_spec,
    waiting_rows,
)
from backend.config import settings
from backend.explore_score import rank_candidates
from backend.locale_check import observe_page, remember_locale, write_locale
from backend.release_row import load_saved_crawl, save_crawl_progress
from backend.run_rules import locale_for, schema_for
from backend.schema_diff import diff_specs
from backend.scrape_seed import harvest_openapi_operations
from backend.swarm import is_payment_url


def test_the_live_frontier_opens_a_higher_score_first_and_keeps_the_menu_first():
    queue = _Frontier(("https://shop.example/", 0, True, False))
    assert queue.popleft()[0] == "https://shop.example/"
    priorities = ["search"]
    links = [
        ("https://shop.example/about", 3, True, False),
        ("https://shop.example/search", 2, True, False),
        ("https://shop.example/help", 1, True, False),
    ]
    for item in links:
        assert place_link(queue, item, priorities=priorities)
    assert place_link(queue, ("https://shop.example/account", 1, True, True), priorities=priorities)
    assert place_link(queue, ("https://shop.example/recruitment", 1, True, False), menu=True)
    assert place_link(queue, ("https://shop.example/product/plain", 4, True, False), known=True,
                      priorities=priorities)
    assert place_link(queue, ("https://shop.example/product/search-result", 4, True, False), known=True,
                      priorities=priorities)
    assert place_link(queue, ("https://shop.example/checkout", 1, True, False)) is True
    assert place_link(queue, ("https://shop.example/payments/card", 1, True, False)) is True
    order = [item[0] for item in queue]
    assert order[0] == "https://shop.example/account"
    assert order[1] == "https://shop.example/recruitment"
    normal = [url for url in order if url in {item[0] for item in links}]
    ranked = [row["url"] for row in rank_candidates([
        {"url": url, "new_template": True, "changed": any(token in url for token in priorities),
         "journey_distance": depth}
        for url, depth, _inside, _auth in links
    ])]
    assert normal == ranked
    later = [url for url in order if "/product/" in url]
    assert later == ["https://shop.example/product/search-result", "https://shop.example/product/plain"]
    payment = [url for url in order if is_payment_url(url)]
    assert payment == ["https://shop.example/checkout", "https://shop.example/payments/card"]
    assert order.index(payment[0]) > order.index(normal[-1])
    assert order.index(payment[-1]) < order.index(later[0])
    assert click_actions_allowed("https://shop.example/product/plain") is True
    assert click_actions_allowed("https://shop.example/checkout") is False
    assert click_actions_allowed("https://www.paypal.com/cgi-bin/webscr") is False
    assert click_actions_allowed("https://shop.example/index.php?rt=checkout/cart") is True
    assert click_actions_allowed("https://shop.example/index.php?rt=checkout/checkout") is False
    assert click_actions_allowed("https://shop.example/index.php?rt=checkout/confirm") is False
    assert click_page(
        "https://shop.example/product/saree-1", "https://shop.example/checkout",
    ) == "https://shop.example/checkout"
    assert click_actions_allowed(click_page(
        "https://shop.example/product/saree-1", "https://shop.example/cart",
    )) is True


def test_a_guest_page_does_not_count_as_the_logged_in_visit():
    urls, done = resume_seen([
        {"url": "https://shop.example/account", "auth": False},
        {"url": "https://shop.example/product/1", "auth": True},
    ])
    assert urls == {"https://shop.example/account", "https://shop.example/product/1"}
    assert ("https://shop.example/account", False) in done
    assert ("https://shop.example/account", True) not in done
    assert ("https://shop.example/product/1", True) in done
    assert ("https://shop.example/product/1", False) not in done


def test_a_page_put_back_after_the_browser_closes_is_still_waiting(tmp_path):
    save_crawl_progress(tmp_path, [], waiting_rows([
        ("https://shop.example/account", 2, True, True),
    ], []))
    _pages, pending = load_saved_crawl(tmp_path)
    assert pending_visit(pending[0]) == ("https://shop.example/account", True)


def test_a_cut_off_page_is_still_waiting():
    rows = waiting_rows([
        ("https://shop.example/account", 2, True, True),
        ("https://shop.example/next", 1, True, False),
    ], [])
    visits = {(row["url"], row["auth"]) for row in rows}
    assert ("https://shop.example/account", True) in visits
    assert ("https://shop.example/next", False) in visits
    assert [row["auth"] for row in rows if row["url"].endswith("/account")] == [True]


def test_a_waiting_logged_in_page_stays_logged_in_on_resume(tmp_path):
    save_crawl_progress(tmp_path, [], [
        "https://shop.example/about",
        {"url": "https://shop.example/account", "auth": True, "depth": 2, "inside": True},
    ])
    _pages, pending = load_saved_crawl(tmp_path)
    assert pending_visit(pending[0]) == ("https://shop.example/about", False)
    assert pending_visit(pending[1]) == ("https://shop.example/account", True)


def test_locale_file_keeps_only_facts_the_page_showed_and_the_sample(tmp_path, monkeypatch):
    observed: dict = {}
    remember_locale(observed, {
        "language": "en-GB", "date_format": "dd/mm/yyyy", "tax": "20%", "offered": False,
        "text": "Tax included on 17/11/2026",
    })
    remember_locale(observed, {"language": "fr", "locale": {"currency": "EUR"}})
    remember_locale(observed, {"totals": ["₹ 500"], "text": "INR 500"})
    assert observed["language"] == "en-GB"
    assert observed["currency"] == "EUR"
    assert observed["date_format"] == "dd/mm/yyyy"
    assert observed["tax"] == "20%"
    assert observed["offered"] is False
    assert observe_page({"text": "Valid until 17/11/2026. Tax included."}) == {}
    assert observe_page({"title": "Home", "text": "Welcome"}) == {}
    assert observe_page({"totals": ["Total € 12"]}) == {"currency": "€"}
    assert observe_page({"text": "Total ¥ 12"}) == {"currency": "¥"}
    payload = write_locale(tmp_path, observed)
    assert payload["expected"] == {}
    assert set(payload["observed"]) == {"language", "currency", "date_format", "tax", "offered"}
    saved = json.loads((tmp_path / "locale.json").read_text(encoding="utf-8"))
    assert saved == payload
    monkeypatch.setattr(settings, "swarm_sample", 3)
    result = locale_for({
        "run_dir": str(tmp_path),
        "crawl": {"swarm": {"sample": 2}},
        "app_map": [{"itemLinks": {"links": [{}, {}, {}, {}]}}],
    })
    assert result["checked"] is True
    assert result["sample"] == 2
    assert result["sample_unchanged"] is True


def test_the_open_page_reads_lang_and_a_visible_currency():
    html = """<html lang="en-IN"><body>
    <p>Price INR 500</p><p>also ₹ 10</p>
    <a href="https://shop.example/saree">Saree</a>
    <button>Add</button>
    </body></html>"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        data = page.evaluate(EXTRACT_JS)
        browser.close()
    assert data["locale"] == {"language": "en-IN", "currency": "INR"}
    assert any(link["href"].endswith("/saree") for link in data["links"])
    assert data["buttons"]
    observed: dict = {}
    remember_locale(observed, data)
    assert observed == {"language": "en-IN", "currency": "INR"}


def _fetcher(pages: dict[str, str]):
    def fetch(url: str) -> str:
        return pages.get(url, "")
    return fetch


def test_openapi_operations_skip_payment_and_do_not_invent_a_baseline(tmp_path, monkeypatch):
    spec = {
        "openapi": "3.0.0",
        "components": {"schemas": {"Cart": {"type": "object", "properties": {"id": {}, "total": {}}}}},
        "paths": {
            "/cart": {"get": {"tags": ["cart"], "responses": {"200": {"content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/Cart"}}}}}}},
            "/orders": {"post": {"operationId": "createOrder", "responses": {"201": {"content": {
                "application/json": {"schema": {"allOf": [
                    {"properties": {"id": {}}}, {"properties": {"status": {}}},
                ]}}}}}}},
            "/checkout": {"post": {"tags": ["pay"], "responses": {"200": {"content": {"application/json": {
                "schema": {"properties": {"card": {}}}}}}}}},
            "/payments/{id}": {"get": {"responses": {"200": {}}}},
            "/product/buy-saree": {"get": {"responses": {"200": {"content": {"application/json": {
                "schema": {"properties": {"sku": {}}}}}}}}},
        },
    }
    pages = {
        "https://shop.test/openapi.json": json.dumps(spec),
        "https://shop.test/swagger.json": json.dumps({
            "definitions": {"Item": {"properties": {"sku": {}}}},
            "paths": {"/items": {"get": {"operationId": "listItems", "responses": {
                "200": {"schema": {"$ref": "#/definitions/Item"}}}}}},
        }),
    }
    operations = harvest_openapi_operations(_fetcher(pages), "https://shop.test/")
    assert operations is not None
    by_path = {row["path"]: row for row in operations}
    assert set(by_path) == {"/cart", "/orders", "/product/buy-saree", "/items"}
    assert by_path["/cart"] == {"method": "GET", "path": "/cart", "fields": ["id", "total"], "workflow": "cart"}
    assert by_path["/orders"]["workflow"] == "createOrder"
    assert by_path["/orders"]["fields"] == ["id", "status"]
    assert by_path["/items"]["fields"] == ["sku"]
    assert harvest_openapi_operations(_fetcher({}), "https://shop.test/") is None
    only_pay = {"paths": {"/checkout": {"post": {"responses": {"200": {}}}}}}
    assert harvest_openapi_operations(
        _fetcher({"https://shop.test/openapi.json": json.dumps(only_pay)}), "https://shop.test/") == []

    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    run = tmp_path / "run"
    assert store_api_spec(run, operations) is True
    assert store_api_spec(run, None) is False
    assert not (tmp_path / "baseline" / "shop" / "api_spec.json").exists()
    compared = schema_for({"run_dir": str(run), "site_key": "shop"})
    assert compared == {"compared": False, "broken": [], "trust_broken": False}
    current = json.loads((run / "api_spec.json").read_text(encoding="utf-8"))
    previous = {"operations": [{"method": "GET", "path": "/cart", "workflow": "cart", "fields": ["id"]}]}
    diff = diff_specs(previous, current)
    assert diff["trust_broken"] is True
    assert diff["broken"][0]["workflow"] == "cart"
    assert diff["broken"][0]["current_fields"] == ["id", "total"]
