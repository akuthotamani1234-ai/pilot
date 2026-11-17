"""The remaining Qpilot X rules. The listing sample itself is covered in test_swarm.py."""
import pytest

from backend.agent_eval import evaluate, model_change_allowed
from backend.capabilities import run_record
from backend.coverage_verify import verify_sources
from backend.dependency_fault import inject_fault
from backend.env_controls import action_still_blocked, enable_control
from backend.explore_score import rank_candidates
from backend.human_review import decide, withhold_unanswered
from backend.incremental_map import plan_pages
from backend.journey_map import compare_journey
from backend.locale_check import check_locale, keep_sample
from backend.mutation_score import score_planted
from backend.oracle import cart_expected
from backend.plugins import review_plugin
from backend.quality_trends import cluster_runs, keep_verdict
from backend.replay_pack import make_package, replay
from backend.schema_diff import diff_specs
from backend.sessions import RoleBook
from backend.swarm import choose_listing


def test_the_listing_sample_still_keeps_the_first_products_and_blocks_checkout():
    chosen, skipped = choose_listing(
        ["https://shop.example/checkout", "https://shop.example/saree-1", "https://shop.example/saree-2",
         "https://shop.example/saree-3", "https://shop.example/saree-4"],
        2,
    )
    assert chosen == ["https://shop.example/saree-1", "https://shop.example/saree-2"]
    assert skipped[0][0].endswith("/checkout")


def test_the_next_page_score_prefers_a_new_template_and_drops_payment():
    ranked = rank_candidates([
        {"url": "https://shop.example/known", "new_template": False, "journey_distance": 9},
        {"url": "https://shop.example/checkout", "new_template": True},
        {"url": "https://shop.example/new", "new_template": True, "failed": True, "journey_distance": 1},
    ])
    assert [row["url"] for row in ranked] == ["https://shop.example/new", "https://shop.example/known"]
    assert ranked[0]["score"] > ranked[1]["score"]


def test_unknown_coverage_is_not_a_pass_and_a_cart_check_names_its_fields():
    verdict = verify_sources(
        graph=["https://shop.example/a"],
        dom=["https://shop.example/a", "https://shop.example/b"],
        requirements=["https://shop.example/wishlist"],
        blocked=["https://shop.example/checkout"],
    )
    assert verdict["complete"] is False
    assert verdict["missed"] == ["https://shop.example/b"]
    assert verdict["unknown"] == ["https://shop.example/wishlist"]
    ok, reason = cart_expected("ai", {"item": "saree"})
    assert not ok and "person" in reason
    ok, reason = cart_expected("business_rule", {"item": "saree", "price": "100"})
    assert not ok and "tax" in reason
    ok, source = cart_expected(
        "business_rule",
        {"item": "saree", "price": "100", "tax": "5", "discount": "0", "quantity": "1", "fulfillment": "pickup"},
    )
    assert ok and source == "business_rule"


def test_sessions_keep_vault_references_and_record_expiry():
    book = RoleBook("run-1")
    with pytest.raises(ValueError, match="vault"):
        book.add_role("shopper", "secret-password")
    book.add_role("shopper", "vault:shopper")
    book.record_access("shopper", "https://shop.example/orders", opened=False)
    book.expire("shopper")
    public = book.public()
    assert public["roles"]["shopper"]["state"] == "session_expired"
    assert public["roles"]["shopper"]["access"][0]["result"] == "refused"
    assert "secret" not in str(public)


def test_staging_controls_do_not_open_payment_and_production_stays_off():
    ok, name = enable_control("staging", "fixed_clock")
    assert ok and name == "fixed_clock"
    ok, reason = enable_control("production", "network_fault")
    assert not ok and "production" in reason
    blocked, reason = action_still_blocked("pay")
    assert blocked and "blocked" in reason
    fault = inject_fault("production", "payments", permitted=True)
    assert fault["injected"] is False
    fault = inject_fault("staging", "inventory", permitted=True)
    assert fault["injected"] is True and fault["service"] == "inventory"


def test_replay_needs_the_whole_package():
    partial = make_package(environment="staging", actions=["open saree"])
    assert partial["complete"] is False
    assert replay(partial)["ran"] is False
    full = make_package(
        environment="staging", build="42", browser="chromium-120", seed="1",
        starting_state={"cart": 0}, test_data={"tag": "qa-run"}, actions=["open saree", "add"],
        network=[{"url": "/cart"}], screenshots=["cart.png"], assertion="cart shows the saree",
    )
    played = replay(full)
    assert played["ran"] is True and played["steps"] == ["open saree", "add"]


def test_a_missed_planted_defect_is_a_qpilot_defect():
    score = score_planted([{"id": "price"}, {"id": "tax"}], ["price", "invented"])
    assert score["caught"] == ["price"]
    assert score["missed"] == ["tax"]
    assert score["false_reports"] == ["invented"]
    assert score["qpilot_defects"] == ["missed planted defect tax"]


def test_a_journey_difference_fails_only_when_the_spec_requires_a_match():
    steps = {"web": ["search", "open"], "android": ["search", "filter"]}
    reported = compare_journey("find-saree", steps, must_match=False)
    assert reported["status"] == "reported" and reported["failed"] is False
    failed = compare_journey("find-saree", steps, must_match=True)
    assert failed["failed"] is True


def test_a_locale_keeps_the_small_sample():
    result = check_locale(
        {"language": "en", "currency": "INR", "date_format": "dd/mm/yyyy", "tax": "5", "offered": True},
        {"language": "en", "currency": "INR", "date_format": "dd/mm/yyyy", "tax": "5", "offered": True},
    )
    assert result["ok"] is True
    assert keep_sample(3, 4000) == 3
    assert keep_sample(0, 4000) == 0


def test_a_model_change_waits_for_a_stored_evaluation():
    ok, reason = model_change_allowed(None)
    assert not ok and "stored" in reason
    stored = evaluate([
        {"id": "t1", "expected": "pass", "actual": "pass", "cost": 0.1},
        {"id": "t2", "expected": "fail", "actual": "pass", "unsupported": True, "failed": True},
    ])
    assert stored["stored"] is True and stored["unsupported_claims"] == ["t2"]
    ok, _reason = model_change_allowed(stored)
    assert ok


def test_incremental_reopens_changes_and_a_fresh_run_reopens_everything():
    saved = [{"url": "https://shop.example/a", "template": "product", "status": "ok"}]
    current = [
        {"url": "https://shop.example/a", "template": "product", "status": "ok"},
        {"url": "https://shop.example/b", "template": "product", "status": "failed"},
    ]
    planned = plan_pages(saved, current, fresh=False)
    assert planned["smoke"] == ["https://shop.example/a"]
    assert planned["reopen"] == ["https://shop.example/b"]
    fresh = plan_pages(saved, current, fresh=True)
    assert fresh["reopen"] == ["https://shop.example/a", "https://shop.example/b"]
    assert fresh["smoke"] == []


def test_a_schema_change_marks_the_workflow_broken():
    previous = {"operations": [{"method": "GET", "path": "/cart", "workflow": "cart", "fields": ["id", "total"]}]}
    current = {"operations": [{"method": "GET", "path": "/cart", "workflow": "cart", "fields": ["id"]}]}
    diff = diff_specs(previous, current)
    assert diff["trust_broken"] is True
    assert diff["broken"][0]["workflow"] == "cart"


def test_no_answer_leaves_a_sensitive_change_unapplied():
    decision = decide("heal", None)
    assert decision["apply"] is False
    decision = decide("sensitive", "yes")
    assert decision["apply"] is True
    cases, held = withhold_unanswered([
        {"tc_id": "ordinary", "title": "open home"},
        {"tc_id": "pay", "approval_required": True, "title": "pay"},
    ])
    assert held == 1 and [case["tc_id"] for case in cases] == ["ordinary"]


def test_trends_change_priority_without_rewriting_a_verdict():
    trends = cluster_runs([
        {"verdict": "pass", "failures": ["search"], "flaky": ["search"]},
        {"verdict": "fail", "failures": ["cart"], "flaky": []},
    ])
    assert trends["next_priority"][0] == "search"
    assert keep_verdict("pass", trends) == "pass"


def test_a_plugin_cannot_turn_off_the_safety_locks():
    refused = review_plugin({"version": "1", "actions": ["open"], "disable": ["pay", "redact"]})
    assert refused["accepted"] is False and "pay" in refused["reason"]
    accepted = review_plugin({"version": "1", "assertions": ["price is shown"], "notes": ["saree copy"]})
    assert accepted["accepted"] is True and "pay" in accepted["locks"]


def test_the_run_record_leaves_the_sample_unchanged_and_blocks_payment():
    record = run_record(
        run_id="run-1", environment="test", sample=3,
        candidates=[{"url": "https://shop.example/checkout", "new_template": True},
                    {"url": "https://shop.example/saree", "new_template": True}],
        roles=["shopper"], catalog_size=500,
    )
    assert record["sample_unchanged"] is True and record["sample"] == 3
    assert record["locale"]["sample"] == 3
    assert record["explore"]["ranked"][0]["url"].endswith("/saree")
    assert record["environment"]["payment_blocked"] is True
    assert record["dependency"]["production_injected"] is False
    assert record["sessions"]["secrets"] is False
