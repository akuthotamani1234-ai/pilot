"""Gate H: dual-region replication lag contract (not hosted DR).

Records max acceptable replication lag before cutover is blocked. Does **not**
prove hosted multi-region DR — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "dual_region_replication_lag_contract_drill.json"

LOCAL_PARTIAL = (
    "dual_region_store_health_probe_drill.json",
    "failover_rto_drill.json",
    "hosted_dr_rpo_contract_drill.json",
    "hosted_dr_cutover_checklist_drill.json",
    "multi_region_dr_readiness_pack_drill.json",
    "multi_store_dr_drill.json",
)


def run_dual_region_replication_lag_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    contract = {
        "max_lag_seconds": 30,
        "block_cutover_if_exceeded": True,
        "stores": {
            "postgres": {"max_lag_seconds": 30},
            "redis": {"max_lag_seconds": 5},
            "minio": {"max_lag_seconds": 60},
        },
        "probe_evidence": "dual_region_store_health_probe_drill.json",
        "note": "Lag contract only; live hosted multi-region DR still required",
    }
    evidence = {
        "gate_h_complete": False,
        "drill": "dual_region_replication_lag_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "contract": contract,
        "live_hosted_dr": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Dual-region replication lag contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "live hosted multi-region DR / on-call paging still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "dual_region_replication_lag_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = (
            ROOT / "artifacts" / "ops"
            / "dual_region_replication_lag_contract_drill.json"
        )
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
