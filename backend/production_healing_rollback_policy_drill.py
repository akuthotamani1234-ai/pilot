"""Gate E: production healing rollback policy (local, not third-party).

Records when auto-applied locator healing must roll back. Does **not** run a
production / third-party suite — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_rollback_policy_drill.json"

LOCAL_PARTIAL = (
    "production_healing_flaky_policy_drill.json",
    "production_healing_taxonomy_drill.json",
    "production_healing_replay_pack_drill.json",
    "production_healing_acceptance_gate_drill.json",
    "production_healing_fixture_coverage_drill.json",
    "healing_regression_drill.json",
)

TRIGGERS = (
    {"id": "oracle_fail", "action": "rollback", "note": "Healed locator fails oracle"},
    {"id": "auth_redirect", "action": "no_apply", "note": "Auth/401 class never auto-applies"},
    {"id": "infra_error", "action": "no_apply", "note": "Connection/timeout never auto-applies"},
    {"id": "flaky_retry", "action": "hold", "note": "Flaky class held for human review"},
    {"id": "product_defect", "action": "no_apply", "note": "Seeded product defect is not healed"},
)


def run_production_healing_rollback_policy_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_rollback_policy",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "policy_local_only",
        "triggers": list(TRIGGERS),
        "production_suite_executed": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Production healing rollback policy recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "production / third-party healing suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "production_healing_rollback_policy_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = (
            ROOT / "artifacts" / "ops" / "production_healing_rollback_policy_drill.json"
        )
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
