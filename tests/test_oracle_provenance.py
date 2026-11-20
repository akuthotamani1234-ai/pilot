"""Phase 4: oracle assertions need provenance; AI guesses stay needs_review."""
from backend.oracle import bind_assertion, decide_observation


def test_ai_assertion_is_not_an_automatic_defect():
    proposal = bind_assertion(
        source="ai",
        statement="cart total equals price x quantity",
        scope="/cart",
        requirement_id="REQ-CART-1",
    )
    assert proposal["accepted"] is False
    assert proposal["status"] == "needs_review"
    decision = decide_observation(proposal, observed="total wrong", matched=False)
    assert decision["verdict"] == "needs_review"


def test_approved_assertion_can_pass_or_fail_with_provenance():
    assertion = bind_assertion(
        source="business_rule",
        statement="cart total equals price x quantity",
        scope="/cart",
        requirement_id="REQ-CART-1",
    )
    assert assertion["accepted"] is True
    assert assertion["oracle_source"] == "business_rule"
    assert assertion["schema_version"] == 1
    assert decide_observation(assertion, observed="114", matched=True)["verdict"] == "pass"
    failed = decide_observation(assertion, observed="57", matched=False)
    assert failed["verdict"] == "fail"
    assert failed["oracle_source"] == "business_rule"
