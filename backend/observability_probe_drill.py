"""Gate H: observability probe drill (local readiness + evidence inventory).

Records how many ops-readiness checks are ready and how many ops-evidence
artifacts exist. Central metrics/tracing/alerting still open —
``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "observability_probe_drill.json"
OPS_EVIDENCE = ROOT / "docs" / "ops-evidence"


def run_observability_probe_drill(*, ops_dir: Path | None = None) -> dict:
    from .ops_readiness import readiness

    snap = readiness()
    checks = snap.get("checks") if isinstance(snap.get("checks"), dict) else {}
    ready_n = sum(1 for c in checks.values() if isinstance(c, dict) and c.get("ready"))
    total_n = len(checks)
    artifacts = sorted(p.name for p in OPS_EVIDENCE.glob("*.json")) if OPS_EVIDENCE.is_dir() else []
    evidence = {
        "gate_h_complete": False,
        "drill": "observability_probe",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ops_readiness_complete": bool(snap.get("gate_h_complete")),
        "checks_ready": ready_n,
        "checks_total": total_n,
        "evidence_artifacts": len(artifacts),
        "artifact_names_sample": artifacts[:12],
        "ok": total_n > 0 and ready_n > 0 and not bool(snap.get("gate_h_complete")),
        "reason": (
            f"Ops readiness {ready_n}/{total_n} checks ready, {len(artifacts)} evidence "
            "artifacts; central metrics/tracing/alerting still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "observability_probe_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "observability_probe_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
