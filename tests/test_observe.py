"""Observe -> act -> verify -> expand (backend/observe.py) on DemoStore, in a real hidden browser:
the explorer learns what each control does and finds what only an action reveals - a page whose link appears after
'Add to compare', the cart's own controls after 'Add to cart', a help panel's buttons, content that loads when you
scroll down. Protected actions are never performed; on a production site test-account actions aren't either."""
import json

import pytest

from backend.config import settings
from backend.observe import diff, tone
from tests.demo_store import EMAIL, PASSWORD, DemoStore


def _crawl(store, tmp_path_factory, environment="test", max_pages=0):
    from backend.agents.discovery import discovery_agent
    run = tmp_path_factory.mktemp("observe")
    with pytest.MonkeyPatch.context() as mp:
        for k, v in {"test_username": EMAIL, "test_password": PASSWORD, "headless": True, "max_pages": max_pages,
                     "max_depth": 0, "environment": environment}.items():
            mp.setattr(settings, k, v)
        mp.setenv("TEST_USERNAME", EMAIL)
        mp.setenv("TEST_PASSWORD", PASSWORD)
        out = discovery_agent({"url": store.url, "run_dir": str(run), "site_key": "store", "log": []})
    return out, json.loads((run / "crawl.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def explored(tmp_path_factory):
    store = DemoStore().start()
    try:
        out, crawl = _crawl(store, tmp_path_factory)
        yield out, crawl, store
    finally:
        store.stop()


def _page(out, store, path, auth=None):
    return next(p for p in out["app_map"] if (p["url"].replace(store.url, "") or "/") == path
                and (auth is None or bool(p.get("auth")) == auth))


def _learned(page, control):
    return next(b for b in page.get("behaviour", []) if b["control"] == control)


def test_pages_only_an_action_or_scrolling_reveals_are_found(explored):
    out, crawl, store = explored
    paths = {p["url"].replace(store.url, "") or "/" for p in out["app_map"]}
    assert "/weekend" in paths      # only linked from deals that load when you scroll down
    assert "/compare" in paths      # its link appears only after 'Add to compare'
    assert "/checkout" in paths     # the cart shows 'Proceed to checkout' only once something is in it
    assert _page(out, store, "/deals").get("lazy") is True


def test_what_each_control_does_is_recorded_as_evidence(explored):
    out, crawl, store = explored
    product = next(p for p in out["app_map"] if "/product/" in p["url"] and p.get("behaviour"))
    add = _learned(product, "Add to cart")
    assert add["effect"] == "message" and add["tone"] == "ok" and "Added" in add["message"]
    assert _learned(product, "Increase quantity")["effect"] == "value"
    cart = _page(out, store, "/cart")  # read again after 'Add to cart': now with its own quantity controls
    assert cart.get("behaviour") and _learned(cart, "Increase quantity")["message"] == "Cart updated"
    deals = _page(out, store, "/deals", auth=False)
    fav = _learned(deals, "Add to favourites")  # a visitor is asked to sign in: that is not "it works"
    assert fav["tone"] == "login_needed"
    assert _learned(deals, "Notify me")["tone"] == "ok"


def test_controls_revealed_by_another_control_know_their_opener(explored):
    out, crawl, store = explored
    deals = _page(out, store, "/deals", auth=False)
    revealed = {x.get("accname") or x.get("text"): x for x in deals["buttons"] + deals["inputs"] if x.get("revealed_by")}
    assert {"Next tip", "Mark as read"} <= set(revealed)
    assert revealed["Next tip"]["revealed_by"] == "#open-help"
    assert _learned(deals, "Next tip")["revealed_by"] == "#open-help"  # learned with its opener clicked first


def test_protected_actions_are_never_performed_and_every_decision_is_counted(explored):
    out, crawl, store = explored
    for never in ("POST /order", "GET /buy", "GET /logout", "POST /cart/remove", "POST /account"):
        assert never not in store.visited, never
    a = crawl["actions"]
    assert a["attempted"] >= 10 and a["learned"] >= 10 and a["limit_per_page"] == settings.max_interactions_per_page
    blocked = {x["control"] for x in a["blocked_list"]}
    assert {"Buy now", "Place order", "Remove"} <= blocked
    assert all(x["why"].startswith("protected") for x in a["blocked_list"])


def test_production_is_look_only(tmp_path_factory):
    store = DemoStore().start()
    try:
        out, crawl = _crawl(store, tmp_path_factory, environment="production")
    finally:
        store.stop()
    assert not any(v in store.visited for v in ("POST /cart/add", "POST /wishlist/add", "POST /favourites/add"))
    why = {x["control"]: x["why"] for x in crawl["actions"]["blocked_list"]}
    assert why.get("Add to cart", "").startswith("test-account action: only on a test / staging environment")


def _pic(color):
    return f"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='4' height='4'><rect fill='{color}' width='4' height='4'/></svg>"


# like many shops: an image slider whose arrow says "Next" too, a list with its own "Next" page button, and an
# "Add to cart" that answers in the browser's alert box
SLIDER_PAGE = f"""<!doctype html><html><head><title>Shop</title><style>
.carousel-item {{ display: none }} .carousel-item.active {{ display: block }} img {{ width: 200px; height: 80px }}
</style></head><body>
<div id="c" class="carousel slide"><div class="carousel-inner">
  <div class="carousel-item active"><img src="{_pic('red')}" alt="one"></div>
  <div class="carousel-item"><img src="{_pic('blue')}" alt="two"></div>
  <div class="carousel-item"><img src="{_pic('green')}" alt="three"></div></div>
  <a class="carousel-control-next" href="#c" role="button" onclick="slide(event)"><span>Next</span></a></div>
<div class="card"><a href="/item/1">Phone one</a></div><div class="card"><a href="/item/2">Phone two</a></div>
<ul class="pagination"><li><button id="next2" type="button">Next</button></li></ul>
<button id="add" type="button" onclick="alert('Product added.')">Add to cart</button>
<script>function slide(e) {{ e.preventDefault(); const s = [...document.querySelectorAll('.carousel-item')];
  const i = s.findIndex(x => x.classList.contains('active')); s[i].classList.remove('active');
  s[(i + 1) % s.length].classList.add('active'); }}</script></body></html>"""


def test_alert_boxes_slider_arrows_and_pictures_in_a_real_browser():
    """demoblaze.com: 'Add to cart' answers in an alert box (was: 'nothing happened'), and the slider's 'Next'
    arrow was taken for the list's 'Next page' (was: 'Next shows the same items')."""
    import re

    from playwright.sync_api import sync_playwright

    from backend.agents.discovery import EXTRACT_JS
    from backend.agents.script_generator import RESULT_HELPERS
    from backend.features import _page_links
    from backend.observe import DIALOG_INIT_JS, PICTURES_JS, REGION_JS, SNAPSHOT_JS

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            ctx = browser.new_context()
            ctx.add_init_script(DIALOG_INIT_JS)
            ctx.route("http://qa.test/**", lambda r: r.fulfill(body=SLIDER_PAGE, content_type="text/html"))
            page = ctx.new_page()
            page.goto("http://qa.test/")
            data = page.evaluate(EXTRACT_JS)
            arrow = next(b for b in data["buttons"] if "carousel" in (b.get("selector") or ""))
            pager = next(b for b in data["buttons"] if b.get("selector") == "#next2")
            assert arrow["kind"] == "slide" and pager["kind"] == "next"
            assert [x.get("selector") for x in _page_links(dict(data, url="http://qa.test/"))] == ["#next2"]

            before = page.evaluate(SNAPSHOT_JS, None)  # the slider's arrow: another picture, nothing else changes
            pics = page.locator(arrow["selector"]).first.evaluate(REGION_JS)
            page.locator(arrow["selector"]).first.click()
            now = page.evaluate(PICTURES_JS)
            assert pics and now and pics != now and "blue" in now
            assert diff(before, page.evaluate(SNAPSHOT_JS, None), pics != now)["effect"] == "picture"
            assert page.locator("#add").first.evaluate(REGION_JS) is None  # (no widget of its own: the page's pictures)

            before = page.evaluate(SNAPSHOT_JS, None)  # the alert box: written down, then closed as usual
            page.locator("#add").click()
            ev = diff(before, page.evaluate(SNAPSHOT_JS, None))
            assert ev["effect"] == "message" and ev["message"] == "alert: Product added." and ev["tone"] == "ok"
            ns = {"re": re, "pytest": pytest}
            exec(RESULT_HELPERS, ns)
            page.locator("#add").click()
            assert ns["_messages"](page)[-2:] == ["alert: Product added.", "alert: Product added. (2)"]
        finally:
            browser.close()


def test_the_generated_tests_write_down_alert_boxes_and_close_cookie_banners_like_the_explorer():
    from pathlib import Path

    from backend.observe import CLOSE_CONSENT_JS, DIALOG_INIT_JS
    conftest = (Path(__file__).resolve().parents[1] / "backend" / "templates" / "conftest.py").read_text(encoding="utf-8")
    assert DIALOG_INIT_JS in conftest and CLOSE_CONSENT_JS in conftest


def _banner(*buttons):
    clicks = "".join(f'<button onclick="this.parentNode.remove()">{b}</button>' for b in buttons)
    return ('<!doctype html><html><body><h1>Shop</h1><a href="/privacy">Privacy policy</a>'
            '<div id="news" role="dialog" style="position:fixed;top:0;right:0">Subscribe to our newsletter '
            '<button id="news-close">Close</button></div>'
            '<div id="cookies" style="position:fixed;bottom:0;left:0;right:0;background:#eee">We use cookies to '
            f'improve your visit. <a href="/cookies">Cookie policy</a> {clicks}</div></body></html>')


def test_a_cookie_banner_is_closed_with_the_least_consent_and_other_popups_stay():
    from playwright.sync_api import sync_playwright

    from backend.observe import close_consent
    pages = {"/a": _banner("Accept all", "Reject all"), "/b": _banner("Customize", "Accept"),
             "/c": _banner("Got it"), "/d": '<html><body><div style="position:fixed">Subscribe <button>Close</button>'
                                            '</div></body></html>'}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.route("http://qa.test/**", lambda r: r.fulfill(body=pages[r.request.url[len("http://qa.test"):]],
                                                                content_type="text/html"))
            for path, used in (("/a", "Reject all"), ("/b", "Accept"), ("/c", "Got it"), ("/d", "")):
                page.goto("http://qa.test" + path)
                assert close_consent(page) == used, path
                if used:  # the banner is gone, the newsletter popup is still there (not ours to close)
                    assert not page.locator("#cookies").count() and page.locator("#news").is_visible()
        finally:
            browser.close()


def test_the_evidence_rules():
    assert tone("Please sign in to save favourites") == "login_needed"
    assert tone("Unauthorized, can not add product to your favorite list.") == "login_needed"
    assert tone("Something went wrong - the item could not be saved") == "error"
    assert tone("Added Red Apple 1 to your cart") == "ok"
    snap = {"url": "https://x.test/p", "lines": ["Cart (0)"], "values": {"qty": "1"}, "messages": [],
            "controls": ["button|Add|"], "links": ["https://x.test/cart"], "linkTexts": {"https://x.test/cart": "Cart (0)"},
            "items": [], "dialog": False, "headings": ["P"]}
    after = dict(snap, lines=["Cart (1)", "Added to your cart"], messages=["Added to your cart"],
                 linkTexts={"https://x.test/cart": "Cart (1)"})
    ev = diff(snap, after)
    assert ev["effect"] == "message" and ev["tone"] == "ok" and ev["changed_links"] == ["https://x.test/cart"]
    assert diff(snap, dict(snap, values={"qty": "2"}))["effect"] == "value"
    assert diff(snap, dict(snap))["effect"] == "nothing"
    assert diff(snap, dict(snap, url="https://x.test/q"))["effect"] == "navigates"
