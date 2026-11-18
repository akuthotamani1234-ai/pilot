"""The large-shop swarm keeps two or three products and leaves the rest of the list."""
from backend.swarm import assign_workers, choose_listing, is_payment_url, sample_limit


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
    assert not is_payment_url("https://shop.example/product/buy-saree")


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


def test_swarm_size_wins_over_the_older_pattern_sample():
    assert sample_limit(3, 0) == 3
    assert sample_limit(0, 5) == 5
    assert sample_limit(0, 0) == 0
