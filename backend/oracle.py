"""QX-A04 test oracle. An expected result needs a trustworthy source.

An AI suggestion can be stored as a proposal. It is not a passing rule until
a person accepts it, or the source is already an approved rule, contract,
fixture, or baseline.
"""
APPROVED_SOURCES = frozenset({"requirement", "business_rule", "contract", "fixture", "baseline", "human"})


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
