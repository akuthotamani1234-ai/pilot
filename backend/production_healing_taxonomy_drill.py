"""Gate E: production-like failure taxonomy + healing policy cross-check.

Classifies auth/infra/flaky/timeout/locator/assertion samples and re-checks
locator-only heal vs assertion-weaken denial. Production / third-party healing
suite still open — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agents.failure_analysis import classify
from .healing_policy import review_repair

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_taxonomy_drill.json"

SAMPLES = (
    {
        "id": "auth-401",
        "outcome": "failed",
        "error_type": "Error",
        "error": "HTTP 401 Unauthorized — redirected to login page",
        "flaky": False,
        "expect": "auth_problem",
    },
    {
        "id": "infra-refused",
        "outcome": "failed",
        "error_type": "Error",
        "error": "net::ERR_CONNECTION_REFUSED at http://127.0.0.1:9/",
        "flaky": False,
        "expect": "infrastructure",
    },
    {
        "id": "flaky-retry",
        "outcome": "failed",
        "error_type": "TimeoutError",
        "error": "Timeout 5000ms exceeded waiting for locator",
        "flaky": True,
        "expect": "flaky",
    },
    {
        "id": "timeout-slow",
        "outcome": "failed",
        "error_type": "TimeoutError",
        "error": "Test timeout of 30000ms exceeded",
        "flaky": False,
        "expect": "timeout",
    },
    {
        "id": "locator-missing",
        "outcome": "failed",
        "error_type": "TimeoutError",
        "error": "Locator.click: Timeout waiting for locator(\"#missing\")",
        "flaky": False,
        "expect": "locator",
    },
    {
        "id": "assert-product",
        "outcome": "failed",
        "error_type": "AssertionError",
        "error": "AssertionError: expected cart total $42 got $0",
        "flaky": False,
        "expect": "product_defect",
    },
)


def run_production_healing_taxonomy_drill(*, ops_dir: Path | None = None) -> dict:
    rows = []
    for sample in SAMPLES:
        cat, why, conf = classify(sample)
        rows.append({
            "id": sample["id"],
            "category": cat,
            "confidence": conf,
            "why": (why or "")[:120],
            "expect": sample["expect"],
            "matched": cat == sample["expect"],
        })
    old = (
        "def test_prod(page):\n"
        "    page.locator(\"#qpilot-prod-missing\").click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    healed = (
        "def test_prod(page):\n"
        "    page.locator(\"a, button\").first.click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    weakened = (
        "def test_prod(page):\n"
        "    page.locator(\"#qpilot-prod-missing\").click()\n"
        "    assert True\n"
    )
    allow = review_repair(old, healed)
    deny = review_repair(old, weakened)
    healing = {
        "locator_repair_allowed": bool(allow.get("allowed")),
        "weaken_denied": not bool(deny.get("allowed")),
    }
    matched = sum(1 for r in rows if r.get("matched"))
    live_matrix = (
        ROOT / "docs" / "ops-evidence" / "production_healing_matrix_drill.json"
    ).is_file()
    ok = (
        matched == len(rows)
        and healing["locator_repair_allowed"]
        and healing["weaken_denied"]
        and live_matrix
    )
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_taxonomy",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows": rows,
        "matched": matched,
        "total": len(rows),
        "healing": healing,
        "live_matrix_present": live_matrix,
        "ok": ok,
        "reason": (
            f"Production healing taxonomy {matched}/{len(rows)} matched "
            f"(heal allow={healing['locator_repair_allowed']}, "
            f"weaken denied={healing['weaken_denied']}); "
            "production / third-party suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "production_healing_taxonomy_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "production_healing_taxonomy_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
