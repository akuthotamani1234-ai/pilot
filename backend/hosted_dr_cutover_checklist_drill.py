"""Gate H: hosted DR cutover checklist (local rehearsal evidence, not hosted).

Scores cutover checklist items against local dual-region evidence.
Does **not** prove hosted multi-region DR — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_dr_cutover_checklist_drill.json"

CHECKLIST = (
    ("primary_health", "dual_region_store_health_probe_drill.json", "Primary store health probe"),
    ("multi_store", "multi_store_dr_drill.json", "Multi-store DR pack"),
    ("failover_rto", "failover_rto_drill.json", "Failover RTO measured"),
    ("cutover_rehearsal", "multi_region_cutover_rehearsal_drill.json", "Cutover rehearsal pack"),
    ("dr_readiness_pack", "multi_region_dr_readiness_pack_drill.json", "DR readiness pack"),
    ("oncall_pack", "hosted_oncall_readiness_pack_drill.json", "On-call readiness pack"),
    ("paging_escalation", "paging_escalation_ack_pack_drill.json", "Paging escalation+ack pack"),
    ("observability", "observability_probe_drill.json", "Observability probe"),
)


def _linked_checklist() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "hosted_dr_cutover_checklist",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_dr_cutover_checklist_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "hosted_dr_cutover_checklist_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_checklist()

    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for key, artifact, label in CHECKLIST:
        path = ops / artifact
        ready = (not folder_is_linked(path)) and path.is_file()
        rows.append({
            "id": key,
            "artifact": artifact,
            "label": label,
            "ready": ready,
            "hosted_verified": False,
        })
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_h_complete": False,
        "drill": "hosted_dr_cutover_checklist",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "checklist_local_only",
        "score": score,
        "score_of": len(CHECKLIST),
        "checklist": rows,
        "live_hosted_dr": False,
        "ok": score == len(CHECKLIST),
        "reason": (
            f"Hosted DR cutover checklist {score}/{len(CHECKLIST)}; "
            "live hosted multi-region DR / on-call still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_checklist()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_checklist()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
