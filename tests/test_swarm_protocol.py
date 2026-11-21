"""Critical swarm base: handoffs, an independent coverage check, and the oracle rule."""
from backend.coverage_verify import verify_listing
from backend.oracle import accept_expected
from backend.swarm_protocol import Lease, accept_result, new_task, tasks_for_listing, validate_task


def test_a_handoff_needs_a_budget_and_a_role():
    task = new_task(role="worker", url="https://shop.example/product/1", action_budget=0)
    problems = validate_task(task)
    assert "action_budget must be greater than zero" in problems


def test_completed_work_needs_evidence_and_payment_cannot_complete():
    done = new_task(role="worker", url="https://shop.example/product/1", status="completed")
    ok, reason = accept_result(done)
    assert not ok and "evidence" in reason
    done["evidence"] = [{"kind": "browser_observation", "artifact": "swarm_work.json"}]
    ok, reason = accept_result(done)
    assert ok and reason == ""
    pay = new_task(role="worker", url="https://shop.example/checkout", status="completed",
                   reason="checkout, payment and placing an order are never tested",
                   evidence=[{"kind": "browser_observation", "artifact": "swarm_work.json"}])
    ok, reason = accept_result(pay)
    assert not ok and "cannot be completed" in reason


def test_a_sensitive_task_waits_for_a_person():
    task = new_task(role="worker", url="https://shop.example/account/delete", status="completed",
                    approval_required=True,
                    evidence=[{"kind": "browser_observation", "artifact": "swarm_work.json"}])
    ok, reason = accept_result(task)
    assert not ok and "person" in reason
    task["approved"] = True
    ok, _reason = accept_result(task)
    assert ok


def test_one_address_has_one_owner():
    lease = Lease()
    assert lease.claim("https://shop.example/product/1", "worker-1")
    assert not lease.claim("https://shop.example/product/1", "worker-2")
    lease.release("https://shop.example/product/1", "worker-1")
    assert lease.claim("https://shop.example/product/1", "worker-2")


def test_listing_tasks_block_checkout_and_name_a_parent():
    tasks = tasks_for_listing(
        "https://shop.example/search?q=saree",
        ["https://shop.example/product/1", "https://shop.example/product/2"],
        [("https://shop.example/checkout", "checkout, payment and placing an order are never tested")],
        2,
    )
    assert tasks[0]["role"] == "leader" and tasks[0]["status"] == "completed"
    workers = [task for task in tasks if task["role"] == "worker" and task["status"] == "partial"]
    blocked = [task for task in tasks if task["status"] == "blocked"]
    assert len(workers) == 2
    assert all(task["parent_task_id"] == tasks[0]["task_id"] for task in tasks[1:])
    assert blocked[0]["url"].endswith("/checkout")
    assert all(not validate_task(task) for task in tasks)


def test_coverage_check_catches_a_product_nobody_accounted_for():
    urls = ["https://shop.example/a", "https://shop.example/b", "https://shop.example/checkout"]
    verdict = verify_listing(
        urls,
        ["https://shop.example/a"],
        [("https://shop.example/checkout", "checkout, payment and placing an order are never tested")],
    )
    assert verdict["complete"] is False
    assert verdict["missed"] == ["https://shop.example/b"]
    assert verdict["blocked"][0]["url"].endswith("/checkout")
    full = verify_listing(
        urls,
        ["https://shop.example/a"],
        [
            ("https://shop.example/b", "swarm left this product; 1 of 2 on this list were chosen"),
            ("https://shop.example/checkout", "checkout, payment and placing an order are never tested"),
        ],
    )
    assert full["complete"] is True
    assert full["missed"] == []


def test_an_ai_guess_is_not_a_passing_rule():
    ok, reason = accept_expected("ai")
    assert not ok and "person" in reason
    ok, source = accept_expected("ai", reviewed=True)
    assert ok and source == "human"
    ok, source = accept_expected("business_rule")
    assert ok and source == "business_rule"
    ok, reason = accept_expected("")
    assert not ok and "approved source" in reason
