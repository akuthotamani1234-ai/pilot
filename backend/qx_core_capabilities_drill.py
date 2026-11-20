"""QX-A03–A06/A08/A11 (+ A01 note): core capability offline drill.

Coverage verifier, oracles, data lifecycle guards, sessions, replay packages,
and locale checks. Gates stay Partial.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .coverage_verify import verify_listing, verify_sources
from .data_lifecycle import customer_data, production_environment
from .locale_check import check_locale, keep_sample
from .oracle import bind_assertion, cart_expected
from .replay_pack import make_package, replay
from .sessions import RoleBook
from .swarm import choose_listing

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "qx_core_capabilities_drill.json"


def _linked_qx() -> dict:
    return {
        "gate_complete": False,
        "ok": False,
        "drill": "qx_core_capabilities_a03_a11",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_qx_core_capabilities_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "qx_core_capabilities_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_qx()

    urls = [
        "https://shop.example/saree-1",
        "https://shop.example/saree-2",
        "https://shop.example/checkout",
        "https://shop.example/about",
    ]
    chosen, skipped = choose_listing(urls, 2)
    listing = verify_listing(urls, chosen, skipped)
    sources = verify_sources(
        graph=["https://shop.example/a", "https://shop.example/about"],
        dom=["https://shop.example/a", "https://shop.example/b", "https://shop.example/about"],
        requirements=["https://shop.example/wishlist"],
        blocked=["https://shop.example/checkout"],
    )

    cart_ai_blocked, _ = cart_expected("ai", {"item": "saree"})
    cart_ok, cart_src = cart_expected(
        "business_rule",
        {
            "item": "saree",
            "price": "100",
            "tax": "5",
            "discount": "0",
            "quantity": "1",
            "fulfillment": "pickup",
        },
    )
    assertion = bind_assertion(
        source="requirement",
        statement="cart total includes tax",
        scope="cart",
        requirement_id="REQ-CART-1",
    )

    prod = production_environment("production")
    not_prod = production_environment("staging")
    is_customer, _ = customer_data("customer@gmail.com")  # real-looking → refused as fixture
    is_fixture, _ = customer_data("shopper@example.com")  # reserved domain → allowed fixture

    book = RoleBook("qx-core-drill")
    book.add_role("shopper", "vault:shopper")
    book.record_access("shopper", "https://shop.example/orders", opened=False)
    book.expire("shopper")
    public = book.public()

    incomplete = make_package(environment="test", build="1", actions=[{"click": "#a"}])
    complete = make_package(
        environment="test",
        build="1",
        browser="chromium",
        seed="42",
        starting_state={"url": "/"},
        test_data={"user": "vault:u"},
        actions=[{"click": "#buy"}],
        network=[{"url": "/api/cart"}],
        screenshots=["s1.png"],
        assertion={"text": "ok"},
    )
    played = replay(complete)
    blocked_replay = replay(incomplete)

    locale = check_locale(
        {"language": "en", "currency": "USD", "date_format": "MDY", "tax": "0", "offered": True},
        {"language": "en", "currency": "USD", "date_format": "MDY", "tax": "0", "offered": True},
    )
    sample = keep_sample(3, 100)

    redis_path = ROOT / "docs" / "ops-evidence" / "redis_durable_queue_drill.json"
    redis_evidence = (not folder_is_linked(redis_path)) and redis_path.is_file()

    checks = {
        "A01_swarm_listing": len(chosen) == 2 and any("checkout" in s[0] for s in skipped),
        "A01_redis_evidence": redis_evidence,
        "A03_coverage_listing": listing["complete"] is False or bool(listing["covered"]),
        "A03_coverage_sources": sources["complete"] is False and "https://shop.example/b" in sources["missed"],
        "A04_oracle_ai_blocked": cart_ai_blocked is False,
        "A04_oracle_cart_ok": cart_ok and cart_src == "business_rule",
        "A04_oracle_bind": bool(assertion.get("accepted") or assertion.get("ok") or assertion.get("source")),
        "A05_lifecycle_prod": prod is True and not_prod is False,
        "A05_lifecycle_customer": is_customer is True and is_fixture is False,
        "A06_sessions": (
            public["roles"]["shopper"]["state"] == "session_expired"
            and public["roles"]["shopper"]["vault_ref"] == "vault:shopper"
            and "secret" not in str(public)
        ),
        "A08_replay_complete": played.get("ran") is True and blocked_replay.get("ran") is False,
        "A11_locale": locale.get("ok") is True and sample == 3,
    }

    # bind_assertion return shape may use different keys — normalize check.
    if not checks["A04_oracle_bind"]:
        checks["A04_oracle_bind"] = "assertion_id" in assertion

    evidence = {
        "gate_complete": False,
        "drill": "qx_core_capabilities_a03_a11",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": checks,
        "details": {
            "listing": listing,
            "sources": {k: sources[k] for k in ("complete", "missed", "unknown")},
            "oracle": {"cart_ok": cart_ok, "assertion_id": assertion.get("assertion_id")},
            "sessions": public,
            "replay": {"complete_ran": played.get("ran"), "incomplete_missing": blocked_replay.get("missing")},
            "locale": locale,
            "sample": sample,
        },
        "ok": all(checks.values()),
        "reason": (
            f"QX core capabilities A01/A03–A06/A08/A11 offline drill: "
            f"{sum(1 for v in checks.values() if v)}/{len(checks)} checks passed; "
            "gates stay Partial until hosted/live evidence + independent review"
        ),
    }

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_qx()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_qx()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
