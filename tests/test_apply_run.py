"""The blueprint rules run against a finished run, and the listing sample stays put."""
import json

from backend.apply_run import apply_run
from backend.swarm import choose_listing


def test_the_listing_sample_is_not_changed_by_applying_the_rules():
    chosen, skipped = choose_listing(
        ["https://shop.example/checkout", "https://shop.example/one", "https://shop.example/two"],
        2,
    )
    assert chosen == ["https://shop.example/one", "https://shop.example/two"]
    assert skipped[0][0].endswith("/checkout")


def test_a_finished_run_applies_every_rule_and_keeps_its_verdict(tmp_path):
    (tmp_path / "planted.json").write_text(json.dumps([{"id": "price"}, {"id": "tax"}]), encoding="utf-8")
    (tmp_path / "locale.json").write_text(json.dumps({
        "observed": {"language": "en", "currency": "INR", "date_format": "dd/mm/yyyy", "tax": "5", "offered": True},
        "expected": {"language": "en", "currency": "INR", "date_format": "dd/mm/yyyy", "tax": "5", "offered": True},
    }), encoding="utf-8")
    (tmp_path / "journeys.json").write_text(json.dumps([{
        "id": "find-saree", "must_match": False,
        "steps": {"web": ["search", "open"], "android": ["search", "filter"]},
    }]), encoding="utf-8")
    (tmp_path / "api_spec.json").write_text(json.dumps(
        {"operations": [{"method": "GET", "path": "/cart", "workflow": "cart", "fields": ["id"]}]}), encoding="utf-8")
    (tmp_path / "api_spec_previous.json").write_text(json.dumps(
        {"operations": [{"method": "GET", "path": "/cart", "workflow": "cart", "fields": ["id", "total"]}]}),
        encoding="utf-8")
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "note.json").write_text(json.dumps({"version": "1", "notes": ["saree copy"]}), encoding="utf-8")
    (plugins / "bad.json").write_text(json.dumps({"version": "1", "disable": ["pay"]}), encoding="utf-8")
    state = {
        "run_dir": str(tmp_path),
        "run_id": "run-1",
        "environment": "staging",
        "verdict": "Ready with Risks",
        "dependency_fault": "inventory",
        "dependency_permitted": True,
        "requirements": "https://shop.example/wishlist",
        "crawl": {"swarm": {"sample": 3}, "not_visited": ["https://shop.example/missed"], "blocked_requests": []},
        "app_map": [{"url": "https://shop.example/saree", "error": True, "depth": 1, "itemLinks": {"links": [{}, {}, {}]}}],
        "roles": {"shopper": {"pages": {"https://shop.example/orders": "denied"}, "login": "session_expired"}},
        "failures": [{"id": "price", "nodeid": "t::one", "test": "test_cart", "file": "test_cart.py",
                      "page_url": "https://shop.example/saree", "error": "price changed", "category": "product_defect"}],
        "results": [{"nodeid": "t::one", "status": "failed", "screenshot": "cart.png"}],
        "test_cases": [{"tc_id": "cart-1", "title": "Add to cart", "oracle": "ai", "spec": {"item": "saree"}}],
        "healing_log": [{"proposal": True, "nodeid": "t::one", "original_error": "price changed"}],
        "changes": {"incremental": {"reopen": ["https://shop.example/saree"], "smoke": []}},
    }
    applied = apply_run(state, root=tmp_path)
    assert applied["sample_unchanged"] is True and applied["sample"] == 3
    assert applied["locale"]["sample"] == 3 and applied["locale"]["checked"] is True
    assert applied["explore"]["next"][0]["url"].endswith("/saree")
    assert applied["coverage"]["unknown"] == ["https://shop.example/wishlist"]
    assert applied["oracle"][0]["ok"] is False
    assert applied["oracle"][0]["assertion"]["accepted"] is False
    assert applied["oracle"][0]["decision"]["verdict"] == "needs_review"
    assert applied["lifecycle"]["cleanup"]["complete"] is True
    assert applied["healing_policy"]["gate_e_complete"] is False
    assert applied["device_matrix"]["complete"] is False
    assert "web.desktop" in applied["device_matrix"]["verified"]
    assert "android.emulator" in applied["device_matrix"]["unverified"]
    assert applied["portfolios"]["complete"] is False
    assert "locale" in applied["portfolios"]["passed"]
    assert applied["enterprise"]["gate_g_complete"] is False
    assert applied["ops"]["gate_h_complete"] is False
    assert applied["discovery_graph"]["gate_a_complete"] is False
    assert applied["discovery_graph"]["counts"]["nodes"] >= 1
    assert (tmp_path / "discovery_graph.json").is_file()
    assert (tmp_path / "portfolio_gates.json").is_file()
    assert (tmp_path / "surface_coverage.json").is_file()
    assert (tmp_path / "oracle_decisions.json").is_file()
    assert (tmp_path / "lifecycle.json").is_file()
    assert (tmp_path / "healing_policy.json").is_file()
    assert (tmp_path / "visual.json").is_file()
    assert applied["surfaces"]["gate_a_surfaces_complete"] is False
    assert applied["sessions"]["roles"]["shopper"]["state"] == "session_expired"
    assert "password" not in json.dumps(applied["sessions"])
    assert applied["environment"]["payment_blocked"] is True
    assert applied["environment"]["controls"]["fixed_clock"] is True
    assert applied["replay"][0]["replay"]["ran"] is True
    assert applied["mutation"]["missed"] == ["tax"]
    assert applied["journeys"][0]["status"] == "reported"
    assert applied["schema"]["trust_broken"] is True
    assert applied["dependency"]["injected"] is True
    assert applied["review"][0]["apply"] is False
    assert applied["trends"]["verdict"] == "Ready with Risks"
    assert applied["evaluation"]["model_change_allowed"] is True
    names = {row["file"]: row["accepted"] for row in applied["plugins"]}
    assert names["note.json"] is True and names["bad.json"] is False
    assert applied["incremental"]["reopen"] == ["https://shop.example/saree"]
