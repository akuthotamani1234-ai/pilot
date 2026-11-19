"""Gate E: production healing suite budget contract (not third-party live).

Records time/cost/failure budgets expected before a third-party healing suite
can run. Does **not** execute production suite — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_budget_contract_drill.json"

LOCAL_PARTIAL = (
    "production_healing_third_party_sla_drill.json",
    "production_healing_acceptance_gate_drill.json",
    "production_healing_human_loop_contract_drill.json",
    "production_healing_rollback_policy_drill.json",
    "production_healing_suite_pack_drill.json",
    "multi_app_healing_suite_drill.json",
)


def _linked_budget() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "production_healing_budget_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_production_healing_budget_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "production_healing_budget_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_budget()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    budget = {
        "max_wall_minutes": 90,
        "max_ai_calls": 200,
        "max_auto_applies": 25,
        "abort_on_auth_infra": True,
        "human_approval_required_classes": [
            "flaky", "auth_problem", "infrastructure", "product_defect", "timeout",
        ],
        "note": "Budget contract only; production / third-party suite still required",
    }
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_budget_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_local_only",
        "budget": budget,
        "production_suite_executed": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Production healing budget contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "production / third-party healing suite still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_budget()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_budget()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
