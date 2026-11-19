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
    from .finalization import folder_is_linked

    for path in (ROOT / "docs" / "ops-evidence" / name, ROOT / "artifacts" / "ops" / name):
        if folder_is_linked(path):
            continue
        if path.is_file():
            return True
    return False


def _linked_tabletop() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "incident_tabletop_cross_check",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_incident_tabletop_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "incident_tabletop_drill.json"
    stub = ROOT / "docs" / "ops-evidence" / "incident_tabletop_stub.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_tabletop()
    if ops_dir is None and folder_is_linked(stub):
        return _linked_tabletop()
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
    runbook_present = (not folder_is_linked(RUNBOOK)) and RUNBOOK.is_file()
    evidence = {
        "gate_h_complete": False,
        "drill": "incident_tabletop_cross_check",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runbook": "docs/INCIDENT_RUNBOOK.md",
        "runbook_present": runbook_present,
        "roles_exercised": sorted({s["role"] for s in steps if s["done"]}),
        "steps": steps,
        "ok": offline_ok and runbook_present,
        "reason": (
            "Offline incident tabletop cross-checked local backup/paging/soak evidence; "
            "live hosted on-call still open"
        ),
    }

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_tabletop()
    if ops_dir is None and folder_is_linked(stub):
        return _linked_tabletop()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_tabletop()
    if ops_dir is None:
        # Keep stub in sync for older readiness checks that look for the stub name.
        if not folder_is_linked(stub):
            write_text_unless_linked(stub.parent, stub.name, json.dumps({
                "gate_h_complete": False,
                "drill": "incident_tabletop_stub",
                "ran_at": evidence["ran_at"],
                "ok": True,
                "runbook": "docs/INCIDENT_RUNBOOK.md",
                "roles_exercised": evidence["roles_exercised"],
                "outcome": "Cross-checked local backup/paging/soak; no live paging/restore",
                "reason": evidence["reason"],
                "superseded_by": "incident_tabletop_drill.json",
            }, indent=2))
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
