"""Gate H: hosted DR/on-call readiness score (not live paging).

Scores local dual-region + paging + RTO evidence against the hosted on-call
contract. Does **not** page a live rota — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_oncall_readiness_drill.json"

CHECKS = (
    ("multi_region_dr_drill.json", "Local dual-region Postgres failover"),
    ("minio_multi_region_drill.json", "Local MinIO dual-bucket failover"),
    ("redis_multi_region_drill.json", "Local Redis dual-DB failover"),
    ("multi_store_dr_drill.json", "Combined multi-store DR pack"),
    ("failover_rto_drill.json", "Local failover RTO measurement"),
    ("paging_escalation_drill.json", "Loopback primary→secondary paging"),
    ("paging_ack_drill.json", "Loopback paging ack→resolve"),
    ("observability_probe_drill.json", "Local observability probe"),
    ("hosted_oncall_contract_drill.json", "Hosted on-call contract snapshot"),
)


def run_hosted_oncall_readiness_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for name, label in CHECKS:
        ready = (ops / name).is_file()
        rows.append({"artifact": name, "label": label, "ready": ready})
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_h_complete": False,
        "drill": "hosted_oncall_readiness",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "readiness_score_only",
        "score": score,
        "score_of": len(CHECKS),
        "checks": rows,
        "live_hosted_paging": False,
        "ok": score == len(CHECKS),
        "reason": (
            f"Hosted DR/on-call readiness {score}/{len(CHECKS)}; "
            "live hosted multi-region DR / on-call paging still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_oncall_readiness_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_oncall_readiness_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
