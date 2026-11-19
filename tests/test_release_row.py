"""The section 22 steps run in order, and an unauthorized target stops the row."""
import json

from backend.release_row import (
    from_run,
    inventory_pages,
    link_graph,
    load_saved_crawl,
    open_target,
    page_record,
    record_step,
    run_row,
    save_crawl_progress,
)


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


def test_the_row_file_stays_in_order_when_a_later_step_is_stored_first(tmp_path):
    record_step(tmp_path, "seed", {"ok": True, "caught": False, "reason": "no seeded defect"})
    record_step(tmp_path, "register", {"ok": True, "url": "https://shop.example", "scope": "site"})
    stored = json.loads((tmp_path / "row.json").read_text(encoding="utf-8"))
    assert [item["step"] for item in stored["steps"]] == ["register", "seed"]
    assert stored["order"][0] == "register"
    record = page_record({"url": "https://shop.example/saree", "page_type": "product",
                          "buttons": [{"text": "Add"}], "screenshot": "saree.png"})
    assert record["template"] == "product" and record["elements"] == ["Add"]


def test_a_release_row_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = b"tenant-b-only-release"
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_bytes(secret)
    (other / "row.json").write_bytes(secret)
    (other / "app_map.json").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert record_step(linked / "run", "seed", {"ok": True, "reason": "local"}) == {}
    save_crawl_progress(linked / "run", [{"url": "https://shop.example/saree"}], ["https://shop.example/cart"])
    assert (other / "keep.txt").read_bytes() == secret
    assert (other / "row.json").read_bytes() == secret
    assert (other / "app_map.json").read_bytes() == secret
    assert not (other / "run").exists()

    real = tmp_path / "real"
    real.mkdir()
    record_step(real, "seed", {"ok": True, "reason": "local"})
    save_crawl_progress(real, [{"url": "https://shop.example/saree"}], ["https://shop.example/cart"])
    stored = (real / "row.json").read_text(encoding="utf-8")
    assert "local" in stored and secret.decode() not in stored
    assert "saree" in (real / "app_map.json").read_text(encoding="utf-8")
    pages, pending = load_saved_crawl(real)
    assert pages[0]["url"].endswith("/saree")
    assert pending == ["https://shop.example/cart"]
    assert load_saved_crawl(linked / "run") == ([], [])
    assert (other / "keep.txt").read_bytes() == secret


def test_a_continue_button_that_opens_checkout_is_not_safe_work():
    record = page_record({
        "url": "https://shop.example/saree",
        "page_type": "product",
        "buttons": [
            {"text": "Add"},
            {"text": "Continue", "form_action": "/checkout"},
            {"text": "Continue", "onclick": "location='/checkout'"},
        ],
        "links": [{"text": "Cart", "href": "/cart"}],
    })
    assert [item["safe"] for item in record["actions"] if item["name"] == "Continue"] == [False, False]
    assert [item["safe"] for item in record["actions"] if item["name"] == "Add"] == [True]
    assert [item["safe"] for item in record["actions"] if item["name"] == "Cart"] == [True]
    graph = link_graph([page_record({
        "url": "https://shop.example/saree", "page_type": "product",
        "buttons": [{"text": "Add"}],
        "links": [{"text": "Pay", "href": "/checkout"}, {"text": "Cart", "href": "/cart"}],
    })])
    assert [item["to"] for item in graph["transitions"]] == ["/cart"]
    found = inventory_pages([record], done=[], page_budget=5)
    assert [item["action"] for item in found["safe_states"]] == ["Add", "Cart"]


def test_a_saved_crawl_can_continue_and_a_zero_budget_uses_the_cap(tmp_path):
    save_crawl_progress(tmp_path, [{"url": "https://shop.example/saree"}], ["https://shop.example/next"])
    pages, pending = load_saved_crawl(tmp_path)
    assert pages[0]["url"].endswith("/saree")
    assert pending == ["https://shop.example/next"]
    registered = open_target(url="https://shop.example", scope="site", page_budget=0, hard_cap=50,
                             time_budget_min=30, authorized=True)
    assert registered["ok"] is True and registered["page_budget"] == 50
    refused = open_target(url="https://shop.example", scope="site", page_budget=10, hard_cap=50,
                          time_budget_min=30, authorized=False)
    assert refused["ok"] is False


def test_a_finished_run_does_not_treat_checkout_continue_as_safe_work(tmp_path):
    (tmp_path / "app_map.json").write_text("[]", encoding="utf-8")
    state = {
        "run_dir": str(tmp_path), "url": "https://shop.example",
        "crawl": {"section": "/", "limit": 5, "time_limit_min": 10, "approved_hosts": ["shop.example"],
                  "swarm": {"workers": 1}},
        "app_map": [{
            "url": "https://shop.example/saree", "page_type": "product",
            "buttons": [
                {"text": "Add"},
                {"text": "Continue", "form_action": "/checkout"},
            ],
        }],
        "test_cases": [], "results": [], "failures": [], "log": ["discovery finished"],
    }
    row = from_run(state)
    actions = {item["action"] for item in row["inventory"]["safe_states"]}
    assert "Add" in actions
    assert "Continue" not in actions


def test_a_checkout_case_is_not_given_to_a_worker():
    from backend.release_row import isolated_work

    rows = isolated_work([
        {"id": "see-price", "source": "business_rule", "assertion": "the price is shown",
         "url": "https://shop.example/saree"},
        {"id": "pay", "source": "business_rule", "assertion": "the order is placed",
         "url": "https://shop.example/checkout"},
        {"id": "confirm", "source": "business_rule", "assertion": "confirm the order",
         "spec": {"url": "https://shop.example/index.php?rt=checkout/confirm"}},
        {"id": "cart", "source": "business_rule", "assertion": "the cart is shown",
         "url": "https://shop.example/index.php?rt=checkout/cart"},
    ], 2)
    by_id = {row["id"]: row for row in rows}
    assert by_id["see-price"]["accepted"] is True and by_id["see-price"]["worker"] == 1
    assert by_id["pay"]["accepted"] is False and by_id["pay"]["worker"] == 0
    assert "checkout" in by_id["pay"]["reason"]
    assert by_id["confirm"]["accepted"] is False and "checkout" in by_id["confirm"]["reason"]
    assert by_id["cart"]["accepted"] is True and by_id["cart"]["worker"] == 2


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


def test_a_crawl_record_does_not_follow_a_link_into_another_run(tmp_path):
    import json
    from pathlib import Path

    from backend.agents.discovery import store_api_spec
    from backend.finalization import write_text_unless_linked
    from backend.release_row import read_target

    secret = "tenant-b-only-crawl"
    other = tmp_path / "other"
    other.mkdir()
    (other / "app_map.json").write_text(json.dumps([{"url": secret}]), encoding="utf-8")
    (other / "crawl_progress.json").write_text(json.dumps({"pending": [secret]}), encoding="utf-8")
    (other / "target.json").write_text(json.dumps({"url": secret, "ok": True}), encoding="utf-8")
    (other / "api_spec.json").write_text(json.dumps({"operations": [secret]}), encoding="utf-8")
    (other / "swarm_work.json").write_text(json.dumps([{"secret": secret}]), encoding="utf-8")

    run = tmp_path / "run"
    run.mkdir()
    for name in ("app_map.json", "crawl_progress.json", "target.json", "api_spec.json", "swarm_work.json"):
        (run / name).symlink_to(other / name)

    save_crawl_progress(run, [{"url": "https://shop.example/ours"}], ["https://shop.example/next"])
    pages, pending = load_saved_crawl(run)
    assert pages == [] and pending == []
    assert read_target(run) is None
    assert store_api_spec(run, [{"method": "GET", "path": "/ours"}]) is False
    assert write_text_unless_linked(run, "swarm_work.json", json.dumps([{"work": "ours"}])) is False
    for name in ("app_map.json", "crawl_progress.json", "target.json", "api_spec.json", "swarm_work.json"):
        assert secret in (other / name).read_text(encoding="utf-8")

    own = tmp_path / "own"
    save_crawl_progress(own, [{"url": "https://shop.example/ours"}], ["https://shop.example/next"])
    pages, pending = load_saved_crawl(own)
    assert pages[0]["url"].endswith("/ours")
    assert pending == ["https://shop.example/next"]
    assert store_api_spec(own, [{"method": "GET", "path": "/ours"}]) is True
    assert Path(own / "api_spec.json").is_file()
