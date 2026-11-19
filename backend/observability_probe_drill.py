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


def _linked_probe() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "observability_probe",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def _artifact_names() -> list[str]:
    from .finalization import folder_is_linked

    if folder_is_linked(OPS_EVIDENCE) or not OPS_EVIDENCE.is_dir():
        return []
    names = []
    for path in OPS_EVIDENCE.glob("*.json"):
        if folder_is_linked(path):
            continue
        names.append(path.name)
    return sorted(names)


def run_observability_probe_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    from .ops_readiness import readiness

    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_probe()

    snap = readiness()
    checks = snap.get("checks") if isinstance(snap.get("checks"), dict) else {}
    ready_n = sum(1 for c in checks.values() if isinstance(c, dict) and c.get("ready"))
    total_n = len(checks)
    artifacts = _artifact_names()
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
    text = json.dumps(evidence, indent=2)
    name = "observability_probe_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_probe()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_probe()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
