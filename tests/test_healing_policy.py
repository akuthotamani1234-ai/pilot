"""Gate E: locator-only healing policy rejects assertion edits."""
from backend.healing_policy import review_repair, summarize_healing


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


def test_summarize_healing_stays_incomplete():
    snap = summarize_healing([{"method": "unique-locator", "status": "kept"},
                              {"proposal": True, "accepted": False}])
    assert snap["gate_e_complete"] is False
    assert snap["attempts"] == 2
    assert snap["policy"] == "locator_only"
