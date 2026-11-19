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


def test_an_ai_guess_on_a_contract_case_cannot_become_a_product_defect():
    case = attach_assertion({
        "tc_id": "TC-AI-CONTRACT", "title": "Guess", "expected": "Maybe",
        "oracle": "ai", "contract_id": "checkout", "script_source": "contract",
        "url": "/checkout",
    })
    assert case["assertion"]["accepted"] is False
    cat, _why, decision = soften_defect_category(
        "product_defect", case, {"outcome": "failed", "error_type": "AssertionError"},
    )
    assert cat == "inconclusive"
    assert decision["verdict"] == "needs_review"
    accepted = attach_assertion({
        "tc_id": "TC-AI-OK", "title": "Accepted", "expected": "Total matches",
        "oracle": "ai", "contract_id": "totals", "human_accepted": True, "url": "/cart",
    })
    assert accepted["assertion"]["accepted"] is True
    assert accepted["assertion"]["oracle_source"] == "human"


def test_a_contract_result_that_names_an_ai_oracle_is_not_a_product_defect():
    from backend.agents.failure_analysis import _finding_from_result

    cat, _why, decision = soften_defect_category(
        "product_defect", {},
        {"outcome": "failed", "error_type": "AssertionError", "contract_id": "checkout", "oracle": "ai"},
    )
    assert cat == "inconclusive"
    assert decision["verdict"] == "needs_review"
    finding = _finding_from_result({
        "outcome": "failed", "error_type": "AssertionError", "error": "expected total",
        "contract_id": "checkout", "oracle": "observed", "nodeid": "t.py::test_total",
        "test": "test_total", "file": "t.py", "url": "https://shop.example/checkout",
    }, fid=1)
    assert finding["category"] == "inconclusive"
    assert finding["oracle_decision"]["verdict"] == "needs_review"
    assert "bug" not in finding
    plain = soften_defect_category(
        "product_defect", None, {"outcome": "failed", "contract_id": "totals"},
    )
    assert plain[0] == "product_defect"
    assert plain[2] is None


def test_a_contract_case_without_an_ai_label_stays_an_approved_oracle():
    case = attach_assertion({
        "tc_id": "TC-CONTRACT", "title": "Total", "expected": "Total matches",
        "contract_id": "totals", "url": "/cart",
    })
    assert case["assertion"]["accepted"] is True
    assert case["assertion"]["oracle_source"] == "contract"
    raw = {"tc_id": "TC-RAW", "oracle": "observed", "expected": "Maybe", "url": "/x",
           "contract_id": "pay"}
    cat, _why, decision = soften_defect_category("product_defect", raw, {"outcome": "failed"})
    assert cat == "inconclusive"
    assert decision["verdict"] == "needs_review"
