"""Gate E: production healing human-in-the-loop contract (not third-party).

Records which failure classes require human approval before apply. Does **not**
run a production / third-party suite — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_human_loop_contract_drill.json"

LOCAL_PARTIAL = (
    "production_healing_flaky_policy_drill.json",
    "production_healing_rollback_policy_drill.json",
    "production_healing_taxonomy_drill.json",
    "production_healing_acceptance_gate_drill.json",
    "production_healing_third_party_sla_drill.json",
    "healing_regression_drill.json",
)

CLASSES = (
    {"id": "locator", "auto_apply": True, "human_required": False},
    {"id": "flaky", "auto_apply": False, "human_required": True},
    {"id": "auth_problem", "auto_apply": False, "human_required": True},
    {"id": "infrastructure", "auto_apply": False, "human_required": True},
    {"id": "product_defect", "auto_apply": False, "human_required": True},
    {"id": "timeout", "auto_apply": False, "human_required": True},
)


def _linked_human() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "production_healing_human_loop_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_production_healing_human_loop_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "production_healing_human_loop_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_human()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_human_loop_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_local_only",
        "classes": list(CLASSES),
        "approval_channel": "studio_approvals",
        "production_suite_executed": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Production healing human-loop contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "production / third-party healing suite still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_human()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_human()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
