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


def run_hosted_dr_cutover_checklist_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for key, artifact, label in CHECKLIST:
        ready = (ops / artifact).is_file()
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
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_dr_cutover_checklist_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_dr_cutover_checklist_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
