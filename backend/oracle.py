"""QX-A04 test oracle. An expected result needs a trustworthy source.

An AI suggestion can be stored as a proposal. It is not a passing rule until
a person accepts it, or the source is already an approved rule, contract,
fixture, or baseline. Bound assertions carry provenance and a schema version.
"""
from uuid import uuid4

APPROVED_SOURCES = frozenset({"requirement", "business_rule", "contract", "fixture", "baseline", "human"})
SCHEMA_VERSION = 1


def accept_expected(source: str, *, reviewed: bool = False) -> tuple[bool, str]:
    """Whether this expected result may decide pass or fail."""
    kind = (source or "").strip().lower()
    if kind in APPROVED_SOURCES:
        return True, kind
    if kind in {"ai", "llm", "model"}:
        if reviewed:
            return True, "human"
        return False, "an AI proposal is not a passing rule until a person accepts it"
    return False, "expected behavior needs an approved source"


CART_FIELDS = ("item", "price", "tax", "discount", "quantity", "fulfillment")


def cart_expected(source: str, fields: dict, *, reviewed: bool = False) -> tuple[bool, str]:
    """An add-to-cart check names the item, money, quantity, and fulfillment."""
    ok, reason = accept_expected(source, reviewed=reviewed)
    if not ok:
        return False, reason
    missing = [name for name in CART_FIELDS if fields.get(name) in (None, "")]
    if missing:
        return False, "an add-to-cart check must name " + ", ".join(missing)
    return True, reason


def bind_assertion(*, source: str, statement: str, scope: str, requirement_id: str = "",
                   reviewed: bool = False, confidence: float = 1.0) -> dict:
    """Create a versioned assertion with provenance, or a blocked proposal for AI guesses."""
    ok, resolved = accept_expected(source, reviewed=reviewed)
    base = {
        "assertion_id": uuid4().hex,
        "schema_version": SCHEMA_VERSION,
        "statement": (statement or "").strip(),
        "scope": (scope or "").strip(),
        "requirement_id": (requirement_id or "").strip(),
        "source_requested": (source or "").strip().lower(),
        "confidence": float(confidence),
    }
    if not base["statement"] or not base["scope"]:
        return {**base, "accepted": False, "status": "blocked",
                "oracle_source": "", "reason": "assertion needs a statement and scope"}
    if not ok:
        return {**base, "accepted": False, "status": "needs_review",
                "oracle_source": "", "reason": resolved}
    return {**base, "accepted": True, "status": "active",
            "oracle_source": resolved, "reason": ""}


def decide_observation(assertion: dict, *, observed: str, matched: bool) -> dict:
    """Apply a bound assertion. Unaccepted assertions never become defects."""
    if not assertion.get("accepted"):
        return {"verdict": "needs_review", "reason": assertion.get("reason") or "oracle not accepted",
                "assertion_id": assertion.get("assertion_id"), "observed": observed}
    if matched:
        return {"verdict": "pass", "reason": "", "assertion_id": assertion["assertion_id"],
                "observed": observed, "oracle_source": assertion.get("oracle_source")}
    return {"verdict": "fail", "reason": "observation did not match approved expectation",
            "assertion_id": assertion["assertion_id"], "observed": observed,
            "oracle_source": assertion.get("oracle_source")}
