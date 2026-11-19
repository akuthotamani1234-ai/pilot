"""Gate E: offline healing regression suite (locator-only guards).

Pairs failure shapes with proposed script repairs and records which repairs
the policy allows. Live failure matrix / production healing still open —
gate_e_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .healing_policy import review_repair

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "healing_regression_drill.json"

_BASE = (
    "def test_x(page):\n"
    "    page.locator(\"#a\").click()\n"
    "    assert page.locator(\"#ok\").is_visible()\n"
)

# Controlled repair proposals: only locator edits should pass.
CASES: list[dict] = [
    {
        "id": "locator-swap",
        "category_hint": "test_defect",
        "old": _BASE,
        "new": (
            "def test_x(page):\n"
            "    page.locator(\"#b\").click()\n"
            "    assert page.locator(\"#ok\").is_visible()\n"
        ),
        "expect_allowed": True,
    },
    {
        "id": "assertion-weaken",
        "category_hint": "product_defect",
        "old": _BASE,
        "new": (
            "def test_x(page):\n"
            "    page.locator(\"#a\").click()\n"
            "    assert True\n"
        ),
        "expect_allowed": False,
    },
    {
        "id": "assertion-drop",
        "category_hint": "product_defect",
        "old": _BASE,
        "new": (
            "def test_x(page):\n"
            "    page.locator(\"#a\").click()\n"
        ),
        "expect_allowed": False,
    },
    {
        "id": "get-by-role-locator",
        "category_hint": "test_defect",
        "old": _BASE,
        "new": (
            "def test_x(page):\n"
            "    page.get_by_role(\"button\", name=\"Save\").click()\n"
            "    assert page.locator(\"#ok\").is_visible()\n"
        ),
        "expect_allowed": True,
    },
    {
        "id": "price-assert-change",
        "category_hint": "product_defect",
        "old": (
            "def test_x(page):\n"
            "    assert page.locator(\".price\").inner_text() == \"$10\"\n"
        ),
        "new": (
            "def test_x(page):\n"
            "    assert page.locator(\".price\").inner_text() == \"$12\"\n"
        ),
        "expect_allowed": False,
    },
]


def build_healing_regression(cases: list[dict] | None = None) -> dict:
    rows = []
    mismatches = 0
    for raw in cases or CASES:
        decision = review_repair(raw["old"], raw["new"])
        allowed = bool(decision.get("allowed"))
        expected = bool(raw.get("expect_allowed"))
        match = allowed == expected
        if not match:
            mismatches += 1
        rows.append({
            "id": raw.get("id"),
            "category_hint": raw.get("category_hint"),
            "allowed": allowed,
            "expect_allowed": expected,
            "match": match,
            "reason": (decision.get("reason") or "")[:160],
            "policy": decision.get("policy") or "locator_only",
        })
    return {
        "gate_e_complete": False,
        "drill": "offline_healing_regression_suite",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cases": len(rows),
        "mismatches": mismatches,
        "policy": "locator_only",
        "rows": rows,
        "reason": (
            "Offline locator-only healing regression recorded; live failure matrix / "
            "production healing still open"
        ),
    }


def _linked_regression() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "offline_healing_regression_suite",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_healing_regression_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "healing_regression_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_regression()
    evidence = build_healing_regression()
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_regression()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_regression()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
