"""Gate E: production healing escalation ladder contract (not live suite).

Records when auto-heal must escalate to human / abort. Does **not** run a
production / third-party suite — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_escalation_ladder_drill.json"

LOCAL_PARTIAL = (
    "production_healing_human_loop_contract_drill.json",
    "production_healing_flaky_policy_drill.json",
    "production_healing_rollback_policy_drill.json",
    "production_healing_budget_contract_drill.json",
    "production_healing_acceptance_gate_drill.json",
    "production_healing_suite_pack_drill.json",
)


def run_production_healing_escalation_ladder_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    ladder = [
        {
            "level": 1,
            "name": "auto_locator_heal",
            "allowed": True,
            "classes": ["stale_locator", "missing_text", "layout_shift"],
        },
        {
            "level": 2,
            "name": "auto_retry_with_budget",
            "allowed": True,
            "classes": ["transient_timeout", "network_blip"],
            "requires": ["production_healing_budget_contract_drill.json"],
        },
        {
            "level": 3,
            "name": "human_approval_gate",
            "allowed": False,
            "classes": ["flaky", "auth_problem", "product_defect"],
            "requires": ["production_healing_human_loop_contract_drill.json"],
        },
        {
            "level": 4,
            "name": "abort_and_page",
            "allowed": False,
            "classes": ["infrastructure", "data_corruption", "security"],
            "requires": ["production_healing_rollback_policy_drill.json"],
        },
    ]
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_escalation_ladder",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_local_only",
        "ladder": ladder,
        "production_suite_executed": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL) and len(ladder) == 4,
        "reason": (
            f"Production healing escalation ladder recorded "
            f"({len(ladder)} levels, {len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "production / third-party healing suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "production_healing_escalation_ladder_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = (
            ROOT / "artifacts" / "ops"
            / "production_healing_escalation_ladder_drill.json"
        )
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
