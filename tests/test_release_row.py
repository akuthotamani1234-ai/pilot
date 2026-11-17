"""The section 22 steps run in order, and an unauthorized target stops the row."""
from backend.release_row import from_run, run_row


def _pages():
    return [
        {"url": "https://shop.example/saree", "template": "product", "elements": ["Add"],
         "actions": [{"name": "Add", "safe": True, "to": "https://shop.example/cart"}],
         "evidence": ["saree.png"]},
        {"url": "https://shop.example/checkout", "template": "pay", "elements": ["Pay"],
         "actions": [{"name": "Pay", "safe": False}], "evidence": []},
    ]


def test_the_steps_run_in_order_and_keep_the_six_counts_separate():
    row = run_row(
        url="https://shop.example", scope="/", page_budget=5, time_budget_s=600, authorized=True,
        pages=_pages(), done=["https://shop.example/"], cases=[
            {"id": "see-price", "source": "business_rule", "assertion": "the price is shown"},
            {"id": "guess", "source": "ai", "assertion": "the page looks fine"},
        ],
        worker_count=2, planted_id="price", failures=[{
            "id": "price", "environment": "test", "build": "1", "browser": "chromium", "assertion": "price changed",
            "screenshots": ["price.png"], "actions": ["open the product"], "network": ["recorded"],
            "starting_state": {"cart": 0}, "test_data": {"id": "price"},
        }],
        results=[{"url": "https://shop.example/saree", "status": "passed"},
                 {"url": "https://shop.example/search", "status": "failed"}],
        unknown=["https://shop.example/wishlist"], cancelled=False, retries=1,
        logs=["discovery finished"], backup="app_map.json",
    )
    assert [step["step"] for step in row["steps"]] == [
        "register", "inventory", "graph", "workers", "seed", "dashboard", "operations"]
    assert row["inventory"]["blocked"] == ["https://shop.example/checkout"]
    assert row["inventory"]["safe_states"][0]["action"] == "Add"
    assert row["graph"]["transitions"][0]["to"].endswith("/cart")
    assert row["workers"][0]["isolated"] is True and row["workers"][0]["context"] == "worker-1"
    assert row["workers"][1]["accepted"] is False
    assert row["seed"]["caught"] is True and row["seed"]["replay"]["ran"] is True
    assert list(row["dashboard"]) == ["discovered", "tested", "passed", "failed", "blocked", "unknown"]
    assert row["dashboard"]["unknown"] == 1 and row["dashboard"]["passed"] == 1
    assert row["operations"]["payment_blocked"] is True and row["operations"]["ok"] is True


def test_an_unauthorized_target_stops_before_the_crawl():
    row = run_row(
        url="https://shop.example", scope="/", page_budget=5, time_budget_s=600, authorized=False,
        pages=_pages(), done=[], cases=[], worker_count=1, planted_id="", failures=[], results=[],
        unknown=[], cancelled=False, retries=0, logs=[], backup="",
    )
    assert row["stopped"] == "register"
    assert [step["step"] for step in row["steps"]] == ["register"]
    assert row["dashboard"]["discovered"] == 0


def test_a_finished_run_builds_the_same_row(tmp_path):
    (tmp_path / "app_map.json").write_text("[]", encoding="utf-8")
    state = {
        "run_dir": str(tmp_path), "url": "https://shop.example",
        "crawl": {"section": "/", "limit": 5, "time_limit_min": 10, "approved_hosts": ["shop.example"],
                  "swarm": {"workers": 2}, "not_visited": ["https://shop.example/wishlist"]},
        "app_map": [{"url": "https://shop.example/saree", "page_type": "product", "screenshot": "saree.png",
                     "buttons": [{"text": "Add"}]}],
        "test_cases": [{"tc_id": "see-price", "oracle": "business_rule", "expected": "the price is shown"}],
        "results": [{"url": "https://shop.example/saree", "status": "passed"}],
        "failures": [], "log": ["discovery finished"], "heal_round": 0,
    }
    row = from_run(state)
    assert row["stopped"] == ""
    assert row["dashboard"]["discovered"] == 1
    assert row["dashboard"]["unknown"] == 1
    assert row["workers"][0]["isolated"] is True
    assert row["operations"]["backup_path"] == "app_map.json"
