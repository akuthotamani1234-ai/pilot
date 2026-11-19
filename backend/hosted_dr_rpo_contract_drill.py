"""Gate H: hosted DR RPO / backup retention contract (not live hosted DR).

Records recovery-point objective and backup retention expectations for dual-
region stores. Does **not** prove hosted multi-region DR —
``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_dr_rpo_contract_drill.json"

LOCAL_PARTIAL = (
    "multi_region_dr_drill.json",
    "multi_store_dr_drill.json",
    "failover_rto_drill.json",
    "dual_region_store_health_probe_drill.json",
    "hosted_dr_cutover_checklist_drill.json",
    "multi_region_dr_readiness_pack_drill.json",
    "hosted_oncall_rota_contract_drill.json",
)


def run_hosted_dr_rpo_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    contract = {
        "rpo_minutes": 15,
        "rto_budget_minutes": 30,
        "backup_retention_days": 30,
        "stores": ["postgres", "redis", "minio"],
        "replication": "async_local_dual_region",
        "cutover_evidence": "hosted_dr_cutover_checklist_drill.json",
        "note": "RPO contract only; live hosted multi-region DR still required",
    }
    evidence = {
        "gate_h_complete": False,
        "drill": "hosted_dr_rpo_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "contract": contract,
        "live_hosted_dr": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Hosted DR RPO contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials present); "
            "live hosted multi-region DR / on-call paging still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_dr_rpo_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_dr_rpo_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
