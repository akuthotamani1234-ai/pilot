"""Payment sandboxes: what a test may use to pay - official TEST instruments of a payment provider's sandbox, never
real payment details.

A run may pay only when its owner declares, for that run, that the application is connected to a payment provider's
sandbox / test mode (Jira Execution Center: "Payment sandbox"). Then:
  - the test cases that pay are no longer excluded; the AI gets the provider's official test instruments below,
  - the generated tests may press the order / pay button and open that provider's sandbox pages (SANDBOX_HOSTS),
  - a card-like number typed by a test must be one of the provider's official test numbers - any other is refused
    (templates/conftest.py) in every mode, so a real card can never be typed by a test.
Without a declared sandbox a paying test case is Blocked with what it needs. Production runs never pay.

The instruments are the providers' published test values (their public test documentation); a provider whose
sandbox uses accounts instead of cards (PayPal) takes the sandbox buyer account as a secret of the run.
"""
from __future__ import annotations

import re

PROVIDERS: dict[str, dict] = {
    "stripe": {
        "name": "Stripe (test mode)",
        "cards": {"4242424242424242": "succeeds", "4000000000000002": "declined (generic)",
                  "4000000000009995": "declined (insufficient funds)", "4000002500003155": "needs 3-D Secure"},
        "details": "any future expiry date (e.g. 12/34), any 3-digit CVC, any postal code",
        "hosts": ["checkout.stripe.com", "js.stripe.com", "hooks.stripe.com", "m.stripe.network"],
    },
    "braintree": {
        "name": "Braintree (sandbox)",
        "cards": {"4111111111111111": "succeeds", "4000111111111115": "declined (processor declined)"},
        "details": "any future expiry date, any CVV",
        "hosts": ["sandbox.braintreegateway.com", "assets.braintreegateway.com", "payments.sandbox.braintree-api.com"],
    },
    "adyen": {
        "name": "Adyen (test)",
        "cards": {"4111111111111111": "succeeds (Visa test card)"},
        "details": "expiry 03/2030, CVC 737",
        "hosts": ["checkoutshopper-test.adyen.com", "test.adyen.com"],
    },
    "razorpay": {
        "name": "Razorpay (test mode)",
        "cards": {"4111111111111111": "succeeds (Visa test card)"},
        "details": "any future expiry date, any CVV; the test OTP page offers success / failure",
        "hosts": ["api.razorpay.com", "checkout.razorpay.com"],
    },
    "paypal": {
        "name": "PayPal (sandbox)",
        "cards": {},
        "details": "a PayPal sandbox buyer account (its e-mail and password as secrets of the run)",
        "hosts": ["www.sandbox.paypal.com", "sandbox.paypal.com"],
    },
    "cod": {
        "name": "Cash on delivery / invoice (no card)",
        "cards": {},
        "details": "no payment details are typed",
        "hosts": [],
    },
}
CARD_LIKE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def provider(name: str) -> dict | None:
    return PROVIDERS.get((name or "").strip().lower())


def test_cards(name: str) -> dict[str, str]:
    p = provider(name)
    return dict(p["cards"]) if p else {}


def is_card_like(text: str) -> bool:
    return bool(CARD_LIKE.search(text or ""))


def allowed_card(text: str, name: str) -> bool:
    """A card-like value may be typed only when it is one of this sandbox's official test numbers."""
    digits = re.sub(r"\D", "", text or "")
    return bool(digits) and digits in test_cards(name)


def prompt_rule(name: str) -> str:
    """What the AI is told about paying in this run."""
    p = provider(name)
    if not p:
        return ""
    cards = "; ".join(f"{n} ({what})" for n, what in p["cards"].items()) or "no card"
    return (f"- PAYMENT SANDBOX: this run pays in the {p['name']} sandbox confirmed by the owner. Use ONLY these "
            f"official test payment details: {cards}; {p['details']}. Never type any other card number. You may "
            "place the test order and check its confirmation, order id, totals and payment status.")
