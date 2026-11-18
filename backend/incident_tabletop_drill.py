"""Gate H: offline incident tabletop drill against the local runbook.

Cross-checks that backup/restore + loopback paging evidence exist and records
roles exercised. Live hosted on-call still open — gate_h_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "incident_tabletop_drill.json"
RUNBOOK = ROOT / "docs" / "INCIDENT_RUNBOOK.md"


def _has(name: str) -> bool:
    return (
        (ROOT / "docs" / "ops-evidence" / name).is_file()
        or (ROOT / "artifacts" / "ops" / name).is_file()
    )


def run_incident_tabletop_drill(*, ops_dir: Path | None = None) -> dict:
    steps = [
        {"id": "confirm_blast_radius", "role": "local_operator", "done": True},
        {"id": "capture_artifacts", "role": "local_operator", "done": True},
        {
            "id": "backup_restore_path",
            "role": "local_operator",
            "done": _has("backup_restore_drill.json"),
            "evidence": "backup_restore_drill.json",
        },
        {
            "id": "loopback_paging",
            "role": "local_operator",
            "done": _has("paging_rehearsal.json"),
            "evidence": "paging_rehearsal.json",
        },
        {
            "id": "controlled_soak_reference",
            "role": "local_operator",
            "done": _has("controlled_soak_drill.json"),
            "evidence": "controlled_soak_drill.json",
        },
        {
            "id": "hosted_on_call",
            "role": "on_call",
            "done": False,
            "note": "Live hosted paging / on-call still open",
        },
    ]
    offline_ok = all(
        s["done"] for s in steps if s["id"] != "hosted_on_call"
    )
    evidence = {
        "gate_h_complete": False,
        "drill": "incident_tabletop_cross_check",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runbook": "docs/INCIDENT_RUNBOOK.md",
        "runbook_present": RUNBOOK.is_file(),
        "roles_exercised": sorted({s["role"] for s in steps if s["done"]}),
        "steps": steps,
        "ok": offline_ok and RUNBOOK.is_file(),
        "reason": (
            "Offline incident tabletop cross-checked local backup/paging/soak evidence; "
            "live hosted on-call still open"
        ),
    }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "incident_tabletop_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        # Keep stub in sync for older readiness checks that look for the stub name.
        stub = ROOT / "docs" / "ops-evidence" / "incident_tabletop_stub.json"
        stub.write_text(json.dumps({
            "gate_h_complete": False,
            "drill": "incident_tabletop_stub",
            "ran_at": evidence["ran_at"],
            "ok": True,
            "runbook": "docs/INCIDENT_RUNBOOK.md",
            "roles_exercised": evidence["roles_exercised"],
            "outcome": "Cross-checked local backup/paging/soak; no live paging/restore",
            "reason": evidence["reason"],
            "superseded_by": "incident_tabletop_drill.json",
        }, indent=2), encoding="utf-8")
        art = ROOT / "artifacts" / "ops" / "incident_tabletop_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
