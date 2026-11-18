"""Attach Gate C provenance to test cases and soften AI defects.

Maps design-time oracle labels onto approved sources where safe. AI / observed
expectations stay needs_review and must not become product defects alone.
"""
from __future__ import annotations

from .oracle import bind_assertion, decide_observation

_SOURCE_MAP = {
    "rule": "business_rule",
    "business_rule": "business_rule",
    "requirement": "requirement",
    "contract": "contract",
    "fixture": "fixture",
    "baseline": "baseline",
    "human": "human",
    "observed": "ai",
    "convention": "ai",
    "ai": "ai",
    "llm": "ai",
    "model": "ai",
}


def resolve_source(case: dict) -> str:
    raw = str(case.get("expected_source") or case.get("oracle") or "").strip().lower()
    if case.get("script_source") == "contract" or case.get("contract_id"):
        return "contract"
    if case.get("reviewed") or case.get("human_accepted"):
        return "human"
    return _SOURCE_MAP.get(raw, raw or "ai")


def attach_assertion(case: dict) -> dict:
    """Bind provenance onto one case (mutates and returns the case)."""
    source = resolve_source(case)
    statement = str(case.get("expected") or case.get("title") or "").strip()
    scope = str(case.get("url") or case.get("page") or case.get("tc_id") or "case")
    assertion = bind_assertion(
        source=source,
        statement=statement or "case expectation",
        scope=scope,
        requirement_id=str(case.get("tc_id") or case.get("id") or ""),
        reviewed=bool(case.get("reviewed") or case.get("human_accepted")),
    )
    case["expected_source"] = assertion.get("oracle_source") or source
    case["assertion"] = assertion
    return case


def attach_assertions(cases: list[dict]) -> list[dict]:
    return [attach_assertion(case) for case in cases]


def decision_for_result(case: dict | None, result: dict | None = None) -> dict | None:
    """Decide observation for a bound case. Unaccepted assertions never become defects."""
    if not isinstance(case, dict) or not isinstance(case.get("assertion"), dict):
        return None
    assertion = case["assertion"]
    result = result or {}
    status = str(result.get("status") or result.get("outcome") or result.get("execution_status") or "").lower()
    matched = status in {"passed", "pass"}
    observed = str(result.get("error") or result.get("actual") or status or "")
    return decide_observation(assertion, observed=observed[:500], matched=matched)


def soften_defect_category(category: str, case: dict | None, result: dict | None = None) -> tuple[str, str, dict | None]:
    """Downgrade product_defect when the oracle is not accepted."""
    decision = decision_for_result(case, result)
    if not decision:
        return category, "", None
    if decision.get("verdict") == "needs_review" and category in {
        "product_defect", "assertion_failure", "suspect",
    }:
        reason = decision.get("reason") or "oracle not accepted"
        return "inconclusive", f"Oracle needs review before this can be a product defect: {reason}", decision
    return category, "", decision
