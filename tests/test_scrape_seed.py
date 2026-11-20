"""Non-MCP HTTP scrape seeder: more exploration without Playwright MCP; checkout/payment URLs dropped."""
from backend.scrape_seed import (
    harvest_html_links,
    harvest_json_paths,
    is_pay_checkout_url,
    seed_urls,
)


def test_a_redirect_into_checkout_is_not_read():
    from backend.scrape_seed import _get_text

    seen = []

    class Resp:
        def __init__(self, status, location="", body=""):
            self.status = status
            self.ok = status < 400
            self.headers = {"location": location} if location else {}
            self._body = body

        def text(self):
            return self._body

    class Fetcher:
        def get(self, url, **kwargs):
            seen.append(url)
            assert kwargs.get("max_redirects") == 0
            if str(url).endswith("/home"):
                return Resp(302, "https://shop.test/checkout")
            if str(url).endswith("/product"):
                return Resp(200, body="<a href='/pim'>People</a>")
            if "checkout/cart" in str(url):
                return Resp(200, body="cart")
            if str(url).endswith("/cart"):
                return Resp(302, "https://shop.test/index.php?rt=checkout/cart")
            if str(url).endswith("/guide"):
                return Resp(302, "https://shop.test/index.php?page=checkout")
            if "page=checkout" in str(url):
                return Resp(200, body="pay")
            return Resp(404)

    assert _get_text(Fetcher(), "https://shop.test/home") == ""
    assert seen == ["https://shop.test/home"]
    assert _get_text(Fetcher(), "https://shop.test/product") == "<a href='/pim'>People</a>"
    assert _get_text(Fetcher(), "https://shop.test/cart") == "cart"
    assert _get_text(Fetcher(), "https://shop.test/guide") == ""
    assert "https://shop.test/checkout" not in seen
    assert not any("page=checkout" in u for u in seen)


def test_pay_checkout_urls_are_detected():
    assert is_pay_checkout_url("https://shop.test/checkout")
    assert is_pay_checkout_url("https://shop.test/cart/checkout")
    assert is_pay_checkout_url("https://shop.test/payment?x=1")
    assert is_pay_checkout_url("https://shop.test/app?checkout=1")
    assert is_pay_checkout_url("https://shop.test/index.php?page=checkout")
    assert is_pay_checkout_url("https://shop.test/index.php?step=payment")
    assert is_pay_checkout_url("https://shop.test/index.php?screen=place-order")
    assert is_pay_checkout_url("https://shop.test/#/checkout")
    assert is_pay_checkout_url("https://shop.test/#!/payment")
    assert not is_pay_checkout_url("https://shop.test/#/checkout/cart")
    assert not is_pay_checkout_url("https://shop.test/#top")
    assert not is_pay_checkout_url("https://shop.test/category?page=2")
    assert not is_pay_checkout_url("https://shop.test/checkout-guide")
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
          <loc>https://hr.test/index.php?page=checkout</loc>
          <loc>https://hr.test/index.php?page=2</loc>
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
    assert "https://hr.test/index.php?page=checkout" not in out
    assert "https://hr.test/index.php?page=2" in out

    from backend.scrape_seed import seed_entries
    entries = dict(seed_entries(fetcher, "https://hr.test/",
                                html='<a href="/recruitment/viewCandidates">Candidates</a>'))
    assert entries.get("https://hr.test/pim/viewEmployeeList") == "sitemap"
    assert entries.get("https://hr.test/recruitment/viewCandidates") == "scrape"
    assert entries.get("https://hr.test/leave/viewLeaveList") == "scrape"
