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


def _linked_rpo() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "hosted_dr_rpo_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_dr_rpo_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "hosted_dr_rpo_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_rpo()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
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
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_rpo()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_rpo()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
