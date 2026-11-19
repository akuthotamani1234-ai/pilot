"""The large-shop swarm keeps two or three products and leaves the rest of the list."""
from backend.swarm import (
    SiteSwarm,
    WorkerBrowser,
    assign_workers,
    choose_listing,
    control_opens_payment,
    is_payment_url,
    partition_site,
    perform,
    sample_limit,
)


def test_a_long_saree_list_keeps_three_products():
    urls = [f"https://shop.example/product/saree-{n}" for n in range(1, 11)]
    chosen, skipped = choose_listing(urls, 3)
    assert chosen == urls[:3]
    assert len(skipped) == 7
    assert all("swarm left this product" in reason for _url, reason in skipped)
    assert "3 of 10" in skipped[0][1]


def test_checkout_is_never_given_to_a_worker():
    urls = [
        "https://shop.example/checkout",
        "https://shop.example/product/saree-1",
        "https://shop.example/payment/card",
        "https://shop.example/product/saree-2",
    ]
    chosen, skipped = choose_listing(urls, 3)
    assert chosen == [
        "https://shop.example/product/saree-1",
        "https://shop.example/product/saree-2",
    ]
    assert {url for url, _reason in skipped} == {
        "https://shop.example/checkout",
        "https://shop.example/payment/card",
    }
    assert is_payment_url("https://shop.example/place-order")
    assert is_payment_url("https://shop.example/checkout.html")
    assert is_payment_url("https://shop.example/cart/checkout%2Ehtml")
    assert is_payment_url("https://www.paypal.com/cgi-bin/webscr")
    assert not is_payment_url("https://shop.example/product/buy-saree")
    assert not is_payment_url("https://shop.example/product/checkout-guide")
    assert not is_payment_url("https://notpaypal.com/shop")


def test_a_worker_uses_the_saved_login_for_later_pages():
    class _Context:
        def __init__(self, state):
            self.state = state
            self.closed = False

        def new_page(self):
            return {"state": self.state}

        def close(self):
            self.closed = True

    class _Browser:
        def __init__(self):
            self.contexts = []

        def new_context(self, storage_state=None):
            context = _Context(storage_state)
            self.contexts.append(context)
            return context

    browser = _Browser()
    login = {"state": None}
    worker = WorkerBrowser(browser, login)
    assert worker.page()["state"] is None
    login["state"] = {"cookies": [{"name": "sid", "value": "1"}]}
    assert worker.page()["state"]["cookies"][0]["name"] == "sid"
    assert browser.contexts[0].closed is True
    assert worker.page()["state"]["cookies"][0]["name"] == "sid"
    assert len(browser.contexts) == 2
    worker.close()
    assert browser.contexts[1].closed is True


def test_a_continue_control_that_opens_checkout_is_payment():
    page = "https://shop.example/cart"
    assert control_opens_payment(page, href="/checkout.html")
    assert control_opens_payment(page, href="https://www.paypal.com/cgi-bin/webscr")
    assert control_opens_payment(page, form_action="/payments/card")
    assert control_opens_payment(page, onclick="location='/checkout'")
    assert control_opens_payment(page, href="/cart/checkout%2Ehtml")
    assert not control_opens_payment(page, href="/product/buy-saree")
    assert not control_opens_payment(page, href="index.php?rt=checkout/cart")
    assert not control_opens_payment(page, href="/admin/pay-grades")
    assert not control_opens_payment(page, href="/product/checkout-guide")
    assert not control_opens_payment(page, onclick="location='/cart'")


def test_zero_sample_keeps_the_whole_list():
    urls = [f"https://shop.example/product/{n}" for n in range(4)]
    chosen, skipped = choose_listing(urls, 0)
    assert chosen == urls
    assert skipped == []


def test_each_chosen_product_gets_its_own_worker():
    urls = ["https://shop.example/a", "https://shop.example/b", "https://shop.example/c"]
    plan = assign_workers(urls, 4)
    assert [row["worker"] for row in plan] == [1, 2, 3]
    assert [row["url"] for row in plan] == urls


def test_workers_open_their_products_at_the_same_time_and_leave_checkout_closed():
    opened = []
    notes = []

    def open_page(url):
        opened.append(url)

    rows = perform(
        [
            {"worker": 1, "url": "https://shop.example/product/saree-1"},
            {"worker": 2, "url": "https://shop.example/checkout"},
        ],
        open_page,
        on_status=lambda worker, status, url: notes.append((worker, status, url)),
    )
    assert opened == ["https://shop.example/product/saree-1"]
    assert {row["status"] for row in rows} == {"opened", "blocked"}
    assert (1, "opened", "https://shop.example/product/saree-1") in notes
    assert (2, "blocked", "https://shop.example/checkout") in notes
    assert (1, "finished", "") in notes
    assert (2, "finished", "") in notes


def test_the_whole_website_is_split_across_workers():
    urls = [
        "https://shop.example/",
        "https://shop.example/about",
        "https://shop.example/account",
        "https://shop.example/category/sarees",
        "https://shop.example/checkout",
        "https://shop.example/contact",
    ]
    plan = partition_site(urls, 2, limit=10)
    assert [row["url"] for row in plan] == [
        "https://shop.example/",
        "https://shop.example/about",
        "https://shop.example/account",
        "https://shop.example/category/sarees",
        "https://shop.example/contact",
    ]
    assert {row["worker"] for row in plan} == {1, 2}
    owned = {row["worker"]: [] for row in plan}
    for row in plan:
        owned[row["worker"]].append(row["url"])

    walked = []

    def session():
        mine = []

        def open_page(url):
            mine.append(url)

        def close():
            walked.append(list(mine))

        return open_page, close

    rows = perform(plan, lambda _url: None, session=session)
    assert all(row["status"] == "opened" for row in rows)
    assert sorted(walked) == sorted(owned.values())


def test_other_pages_are_not_pushed_out_by_a_long_product_list():
    urls = [
        "https://shop.example/",
        "https://shop.example/about",
        "https://shop.example/account",
        "https://shop.example/checkout",
    ] + [f"https://shop.example/product/saree-{n}" for n in range(30)]
    plan = partition_site(urls, 3, limit=6)
    chosen = [row["url"] for row in plan]
    assert "https://shop.example/" in chosen
    assert "https://shop.example/about" in chosen
    assert "https://shop.example/account" in chosen
    assert "https://shop.example/checkout" not in chosen
    assert sum(1 for url in chosen if "/product/" in url) < len(chosen)
    assert {row["worker"] for row in plan} == {1, 2, 3}


def test_workers_stay_for_the_whole_run_then_close():
    opened = []
    notes = []

    def session():
        def open_page(url):
            opened.append(url)

        return open_page, lambda: None

    swarm = SiteSwarm(2, 4, session, on_status=lambda worker, status, url: notes.append((worker, status, url)))
    swarm.submit([
        "https://shop.example/",
        "https://shop.example/about",
        "https://shop.example/checkout",
    ])
    swarm.submit([
        "https://shop.example/account",
        "https://shop.example/contact",
        "https://shop.example/help",
    ])
    rows = swarm.finish()
    assert len(rows) == 4
    assert "https://shop.example/checkout" not in {row["url"] for row in rows}
    assert set(opened) == {row["url"] for row in rows}
    assert swarm.submit(["https://shop.example/later"]) == []
    assert any(status == "finished" for _worker, status, _url in notes)


def test_a_worker_reads_the_page_and_saves_what_it_found():
    def session():
        def open_page(url):
            return {"url": url, "title": "Home", "summary": "4 links, 2 buttons, 1 form"}

        return open_page, lambda: None

    notes = []
    swarm = SiteSwarm(1, 2, session, on_status=lambda worker, status, url: notes.append((worker, status, url)))
    swarm.submit(["https://shop.example/"])
    rows = swarm.finish()
    assert rows[0]["work"]["summary"] == "4 links, 2 buttons, 1 form"
    assert (1, "read", "https://shop.example/ | 4 links, 2 buttons, 1 form") in notes


def test_swarm_size_wins_over_the_older_pattern_sample():
    assert sample_limit(3, 0) == 3
    assert sample_limit(0, 5) == 5
    assert sample_limit(0, 0) == 0
