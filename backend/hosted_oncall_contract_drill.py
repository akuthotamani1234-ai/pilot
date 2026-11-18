"""Gate H: hosted multi-region DR / on-call contract snapshot (not live).

Records required dual-region stores, paging tiers, and RTO evidence expected
before hosted ops can close. Does **not** page a live on-call rota —
``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_oncall_contract_drill.json"

LOCAL_PARTIAL = (
    "multi_region_dr_drill.json",
    "minio_multi_region_drill.json",
    "redis_multi_region_drill.json",
    "multi_store_dr_drill.json",
    "failover_rto_drill.json",
    "paging_escalation_drill.json",
    "observability_probe_drill.json",
)


def run_hosted_oncall_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    contract = {
        "regions": ["primary", "secondary"],
        "stores": ["postgres", "minio", "redis"],
        "failover_evidence": "multi_store_dr_drill.json + failover_rto_drill.json",
        "paging_tiers": ["primary", "secondary"],
        "paging_evidence": "paging_escalation_drill.json",
        "observability": "readiness inventory + metrics/tracing/alerting (hosted)",
        "incident_runbook": "docs/INCIDENT_RUNBOOK.md",
        "note": "Live multi-region cutover + pager duty acknowledgement still required",
    }
    evidence = {
        "gate_h_complete": False,
        "drill": "hosted_oncall_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "contract": contract,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Hosted DR/on-call contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials present); "
            "live hosted multi-region DR / on-call paging still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "hosted_oncall_contract_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_oncall_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
