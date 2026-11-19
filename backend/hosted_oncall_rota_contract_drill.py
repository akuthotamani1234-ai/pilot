"""Gate H: hosted on-call rota contract (local, not live paging).

Records rota tiers, ack/resolve SLAs, and escalation schedule expected of a
hosted pager. Does **not** page a live rota — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_oncall_rota_contract_drill.json"

LOCAL_PARTIAL = (
    "paging_escalation_drill.json",
    "paging_ack_drill.json",
    "paging_escalation_ack_pack_drill.json",
    "hosted_oncall_contract_drill.json",
    "hosted_oncall_readiness_drill.json",
    "hosted_oncall_readiness_pack_drill.json",
    "hosted_dr_cutover_checklist_drill.json",
)


def _linked_rota() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "hosted_oncall_rota_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_oncall_rota_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "hosted_oncall_rota_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_rota()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    rota = {
        "tiers": [
            {"name": "primary", "ack_sla_minutes": 5, "resolve_target_minutes": 60},
            {"name": "secondary", "ack_sla_minutes": 15, "resolve_target_minutes": 120},
        ],
        "escalation": {
            "primary_to_secondary_after_minutes": 10,
            "evidence": "paging_escalation_ack_pack_drill.json",
        },
        "channels": ["loopback_webhook", "hosted_pager_pending"],
        "required_actions": ["ack", "resolve", "page_secondary"],
        "note": "Rota contract only; live hosted pager acknowledgement still required",
    }
    evidence = {
        "gate_h_complete": False,
        "drill": "hosted_oncall_rota_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "rota": rota,
        "live_hosted_paging": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Hosted on-call rota contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials present); "
            "live hosted multi-region DR / on-call paging still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_rota()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_rota()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
