"""Pay Grades admin config navigation must not be classified as a payment action (\\bpay\\b false positive).

Real pay/checkout/billing submits stay blocked. No product-specific route hardcoding.
"""
from backend.actions import (
    PAY,
    PROTECTED,
    action_class,
    action_risk,
    blocked_reason,
    is_pay_grade_navigation,
)


def test_pay_grades_link_or_menu_is_not_pay():
    for role in ("link", "menuitem", "tab"):
        assert action_class("Pay Grades", role=role) == "safe"
        assert action_class("Pay Grade", role=role) != "pay"
        assert action_risk("Pay Grades", "a.oxd-main-menu-item", role=role, tag="a") == "safe"
        assert is_pay_grade_navigation("Pay Grades", role=role)
    assert action_class("Pay Grades", kind="menu", tag="a") == "safe"
    assert action_class("Pay Grades", href="/admin/viewPayGrades", tag="a") == "safe"
    assert not PAY.search("Pay Grades")
    assert not PROTECTED.search("Pay Grades")


def test_real_payment_buttons_still_pay_and_blocked_reason_names_permission():
    for label in ("Pay now", "Proceed to payment", "Confirm payment", "Checkout"):
        assert action_class(label) == "pay", label
        assert action_risk(label) == "protected", label
    reason = blocked_reason("pay")
    assert "ALLOW_ACTIONS" in reason and "pay" in reason and "TEST_PAYMENT" in reason
    assert "payment" in reason.lower() or "checkout" in reason.lower()
    # Keyword guards stay tight: unrelated "pay" verbs still match; only pay-grade nav is carved out.
    assert action_class("Buy now") == "pay"
    assert action_class("Place order") == "pay"
