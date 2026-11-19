"""Gate H: hosted DR communications contract (not live hosted DR).

Records status-page / stakeholder notification expectations during cutover.
Does **not** prove hosted multi-region DR — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_dr_comms_contract_drill.json"

LOCAL_PARTIAL = (
    "hosted_dr_cutover_checklist_drill.json",
    "hosted_dr_rpo_contract_drill.json",
    "hosted_oncall_rota_contract_drill.json",
    "paging_escalation_ack_pack_drill.json",
    "multi_region_dr_readiness_pack_drill.json",
    "observability_probe_drill.json",
)


def run_hosted_dr_comms_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    contract = {
        "channels": ["status_page", "pager", "customer_email"],
        "milestones": [
            {"id": "detect", "notify_within_minutes": 5},
            {"id": "cutover_start", "notify_within_minutes": 10},
            {"id": "cutover_complete", "notify_within_minutes": 15},
            {"id": "all_clear", "notify_within_minutes": 30},
        ],
        "required_fields": ["impact", "eta", "region", "next_update_at"],
        "note": "Comms contract only; live hosted multi-region DR still required",
    }
    evidence = {
        "gate_h_complete": False,
        "drill": "hosted_dr_comms_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "contract": contract,
        "live_hosted_dr": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Hosted DR communications contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "live hosted multi-region DR / on-call paging still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_dr_comms_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_dr_comms_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
