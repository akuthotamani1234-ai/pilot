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


def _linked_comms() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "hosted_dr_comms_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_dr_comms_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "hosted_dr_comms_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_comms()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
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
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_comms()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_comms()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
