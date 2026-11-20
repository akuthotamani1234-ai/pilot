"""Gate E: flaky/auth/infra failures must not auto-weaken assertions.

Classifies flaky + auth + infra samples and proves locator-only heal stays
allowed while assertion weaken is denied. Production suite still open —
``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agents.failure_analysis import classify
from .healing_policy import review_repair

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_flaky_policy_drill.json"

SAMPLES = (
    {
        "id": "flaky-timeout",
        "outcome": "failed",
        "error_type": "TimeoutError",
        "error": "Timeout 5000ms exceeded waiting for locator('#cart')",
        "flaky": True,
        "expect": "flaky",
        "auto_apply": False,
    },
    {
        "id": "auth-redirect",
        "outcome": "failed",
        "error_type": "Error",
        "error": "HTTP 401 Unauthorized — login redirect",
        "flaky": False,
        "expect": "auth_problem",
        "auto_apply": False,
    },
    {
        "id": "infra-down",
        "outcome": "failed",
        "error_type": "Error",
        "error": "net::ERR_CONNECTION_REFUSED at http://127.0.0.1:9/",
        "flaky": False,
        "expect": "infrastructure",
        "auto_apply": False,
    },
)


def _linked_policy() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "production_healing_flaky_policy",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_production_healing_flaky_policy_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "production_healing_flaky_policy_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_policy()

    old = (
        "def test_cart(page):\n"
        "    page.locator('#cart-missing').click()\n"
        "    assert page.locator('body').is_visible()\n"
    )
    locator_heal = (
        "def test_cart(page):\n"
        "    page.locator('a, button').first.click()\n"
        "    assert page.locator('body').is_visible()\n"
    )
    weaken = (
        "def test_cart(page):\n"
        "    page.locator('#cart-missing').click()\n"
        "    assert True\n"
    )
    allow = review_repair(old, locator_heal)
    deny = review_repair(old, weaken)
    rows = []
    for sample in SAMPLES:
        cat, why, conf = classify(sample)
        rows.append({
            "id": sample["id"],
            "category": cat,
            "expect": sample["expect"],
            "match": cat == sample["expect"],
            "confidence": conf,
            "why": (why or "")[:120],
            "auto_apply": False,
            "auto_apply_expected": sample["auto_apply"],
        })
    passed = sum(
        1 for row in rows
        if row.get("match") and row.get("auto_apply") is False
    )
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_flaky_policy",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy": {
            "locator_repair_allowed": bool(allow.get("allowed")),
            "assertion_weaken_denied": not bool(deny.get("allowed")),
            "flaky_auth_infra_auto_apply": False,
        },
        "samples": rows,
        "passed": passed,
        "ok": (
            passed == len(SAMPLES)
            and bool(allow.get("allowed"))
            and not bool(deny.get("allowed"))
        ),
        "reason": (
            f"Flaky/auth/infra healing policy {passed}/{len(SAMPLES)} "
            "(no auto-apply; locator-only heal ok); production suite still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_policy()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_policy()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
