"""Non-MCP HTTP scrape seeder: more exploration without Playwright MCP; checkout/payment URLs dropped."""
from backend.scrape_seed import (
    harvest_html_links,
    harvest_json_paths,
    is_pay_checkout_url,
    seed_urls,
)


def test_pay_checkout_urls_are_detected():
    assert is_pay_checkout_url("https://shop.test/checkout")
    assert is_pay_checkout_url("https://shop.test/cart/checkout")
    assert is_pay_checkout_url("https://shop.test/payment?x=1")
    assert is_pay_checkout_url("https://shop.test/app?checkout=1")
    assert not is_pay_checkout_url("https://hr.test/admin/viewPayGrades")
    assert not is_pay_checkout_url("https://hr.test/pim/viewEmployeeList")


def test_html_and_json_harvest_same_host_paths():
    html = """
    <html><a href="/pim/viewEmployeeList">Employees</a>
    <a href="/checkout">Checkout</a>
    <a href="https://other.test/x">Away</a>
    <script>window.__NEXT_DATA__ = {"props":{"page":"/admin/jobTitle"}};</script>
    </html>
    """
    base = "https://hr.test/"
    links = harvest_html_links(html, base)
    assert "https://hr.test/pim/viewEmployeeList" in links
    assert "https://hr.test/checkout" in links
    json_paths = harvest_json_paths(html, base)
    assert any("jobTitle" in u or "/admin/" in u for u in json_paths)


def test_search_seed_words_are_available_for_multi_query_exploration():
    from backend.observe import SEARCH_SEED_WORDS
    assert "admin" in SEARCH_SEED_WORDS and "employee" in SEARCH_SEED_WORDS
    assert len(SEARCH_SEED_WORDS) >= 5


def test_seed_urls_drops_checkout_and_keeps_admin(monkeypatch):
    pages = {
        "https://hr.test/robots.txt": "Sitemap: https://hr.test/sitemap.xml\n",
        "https://hr.test/sitemap.xml": """
        <urlset>
          <loc>https://hr.test/pim/viewEmployeeList</loc>
          <loc>https://hr.test/checkout</loc>
          <loc>https://hr.test/admin/viewPayGrades</loc>
          <loc>https://hr.test/payment</loc>
        </urlset>
        """,
        "https://hr.test/openapi.json": '{"paths": {"/leave/viewLeaveList": {}, "/checkout/pay": {}}}',
    }

    def fetcher(url: str) -> str:
        return pages.get(url, "")

    out = seed_urls(fetcher, "https://hr.test/", html='<a href="/recruitment/viewCandidates">Candidates</a>')
    assert "https://hr.test/pim/viewEmployeeList" in out
    assert "https://hr.test/admin/viewPayGrades" in out
    assert "https://hr.test/recruitment/viewCandidates" in out
    assert "https://hr.test/leave/viewLeaveList" in out
    assert not any(is_pay_checkout_url(u) for u in out)
    assert "https://hr.test/checkout" not in out
    assert "https://hr.test/payment" not in out
