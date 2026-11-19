"""Gate E: production / third-party healing suite contract (not live third-party).

Documents required failure classes, locator-only heal policy, and local evidence
that must exist before a production healing suite can close. Does **not** run
against third-party production — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_contract_drill.json"

LOCAL_PARTIAL = (
    "live_failure_matrix_drill.json",
    "multi_app_healing_suite_drill.json",
    "production_healing_matrix_drill.json",
    "production_healing_taxonomy_drill.json",
    "healing_regression_drill.json",
    "demo_store_healing_live_drill.json",
)


def run_production_healing_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    contract = {
        "required_failure_classes": [
            "locator",
            "product_defect",
            "auth_problem",
            "infrastructure",
            "timeout",
            "flaky",
        ],
        "healing_policy": {
            "locator_only_allowed": True,
            "assertion_weaken_denied": True,
            "module": "backend/healing_policy.py",
        },
        "local_evidence": list(LOCAL_PARTIAL),
        "production_requirements": [
            "Authorized third-party or staging target",
            "Deterministic reproduce of seeded + organic failures",
            "Before/after regression package with replay",
            "Human review of heal proposals outside locator-only",
        ],
        "note": "Local multi-app + taxonomy drills do not substitute for production suite",
    }
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "contract": contract,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Production healing contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials present); "
            "production / third-party healing suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "production_healing_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "production_healing_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
