"""Gate G: freeze remaining-blockers inventory hash for reviewers (unsigned).

Snapshots the hard-open blockers inventory with a content hash so reviewers can
detect drift. Does **not** sign off — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_blocker_freeze_drill.json"


def run_independent_review_blocker_freeze_drill(*, ops_dir: Path | None = None) -> dict:
    from .remaining_blockers_drill import run_remaining_blockers_drill

    blockers = run_remaining_blockers_drill(ops_dir=ops_dir)
    payload = {
        "open_count": blockers.get("open_count"),
        "blockers": [
            {
                "id": row.get("id"),
                "gate": row.get("gate"),
                "label": row.get("label"),
                "status": row.get("status"),
                "local_partial_count": len(row.get("local_partial_present") or []),
                "local_partial_missing": row.get("local_partial_missing") or [],
            }
            for row in (blockers.get("blockers") or [])
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_blocker_freeze",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "unsigned_freeze",
        "freeze": payload,
        "freeze_sha256": digest,
        "signed_off": False,
        "ok": int(blockers.get("open_count") or 0) >= 1 and blockers.get("complete") is False,
        "reason": (
            f"Blocker freeze {digest[:12]}… "
            f"({blockers.get('open_count')} open); external sign-off still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "independent_review_blocker_freeze_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_blocker_freeze_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
