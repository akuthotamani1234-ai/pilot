"""Gate E: locator-only healing policy rejects assertion edits."""
from backend.healing_policy import (
    issue_healing_approval,
    reset_healing_approvals,
    review_repair,
    summarize_healing,
)


def test_repair_may_change_locator_but_not_assertion():
    old = 'def test_x(page):\n    page.locator("#a").click()\n    assert page.locator("#ok").is_visible()\n'
    good = 'def test_x(page):\n    page.locator("#b").click()\n    assert page.locator("#ok").is_visible()\n'
    bad = 'def test_x(page):\n    page.locator("#a").click()\n    assert True\n'
    assert review_repair(old, good)["allowed"] is True
    assert review_repair(old, bad)["allowed"] is False


def test_escalation_blocks_auth_and_infrastructure():
    old = 'def test_x(page):\n    page.locator("#a").click()\n    assert page.locator("#ok").is_visible()\n'
    good = 'def test_x(page):\n    page.locator("#b").click()\n    assert page.locator("#ok").is_visible()\n'
    auth = review_repair(old, good, failure_class="auth_problem")
    infra = review_repair(old, good, failure_class="infrastructure")
    retry = review_repair(old, good, failure_class="timeout")
    assert auth["allowed"] is False
    assert auth["escalation"]["action"] == "human_approval_gate"
    assert infra["allowed"] is False
    assert infra["escalation"]["level"] == 4
    assert retry["allowed"] is True
    assert retry["escalation"]["auto_apply"] is True


def test_human_approval_is_single_use_and_locator_only():
    old = 'def test_x(page):\n    page.locator("#a").click()\n    assert page.locator("#ok").is_visible()\n'
    good = 'def test_x(page):\n    page.locator("#b").click()\n    assert page.locator("#ok").is_visible()\n'
    bad = 'def test_x(page):\n    page.locator("#a").click()\n    assert True\n'
    reset_healing_approvals()
    issued = issue_healing_approval(old, good, "auth_problem")
    assert issued["ok"] is True
    assert issue_healing_approval(old, good, "infrastructure")["ok"] is False
    weaken = issue_healing_approval(old, bad, "auth_problem")
    assert review_repair(
        old, bad, failure_class="auth_problem", approval_token=weaken["token"],
    )["allowed"] is False
    first = review_repair(
        old, good, failure_class="auth_problem", approval_token=issued["token"],
    )
    second = review_repair(
        old, good, failure_class="auth_problem", approval_token=issued["token"],
    )
    reset_healing_approvals()
    assert first["allowed"] is True
    assert second["allowed"] is False
    assert second["reason"] == "healing approval already used"


def test_summarize_healing_stays_incomplete():
    snap = summarize_healing([{"method": "unique-locator", "status": "kept"},
                              {"proposal": True, "accepted": False}])
    assert snap["gate_e_complete"] is False
    assert snap["attempts"] == 2
    assert snap["policy"] == "locator_only"
