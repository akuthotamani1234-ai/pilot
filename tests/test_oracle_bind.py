"""Gate C: design-time provenance and failure softening for unaccepted oracles."""
from backend.oracle_bind import attach_assertion, soften_defect_category


def test_rule_oracle_maps_to_business_rule():
    case = attach_assertion({
        "tc_id": "TC-ABCD1234", "title": "Search works", "expected": "Results show",
        "oracle": "rule", "url": "/search",
    })
    assert case["assertion"]["accepted"] is True
    assert case["assertion"]["oracle_source"] == "business_rule"


def test_ai_oracle_blocks_product_defect():
    case = attach_assertion({
        "tc_id": "TC-AI000001", "title": "Guess", "expected": "Maybe",
        "oracle": "ai", "url": "/x",
    })
    assert case["assertion"]["accepted"] is False
    cat, why, decision = soften_defect_category("product_defect", case, {"outcome": "failed"})
    assert cat == "inconclusive"
    assert "needs review" in why.lower() or "oracle" in why.lower()
    assert decision["verdict"] == "needs_review"
