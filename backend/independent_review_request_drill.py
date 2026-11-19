"""Gate G: unsigned independent-review request receipt.

Packages reviewer handoff fields (summary path, checklist, blockers, pack hash
inputs) so a human can start sign-off. Does **not** sign off —
``signed_off`` stays False and Gate G stays open.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_request_drill.json"


def run_independent_review_request_drill(*, ops_dir: Path | None = None) -> dict:
    from .independent_review_pack_drill import run_independent_review_pack_drill
    from .independent_review_readiness_drill import run_independent_review_readiness_drill
    from .independent_review_summary_drill import run_independent_review_summary_drill
    from .remaining_blockers_drill import run_remaining_blockers_drill

    pack = run_independent_review_pack_drill(ops_dir=ops_dir)
    ready = run_independent_review_readiness_drill(ops_dir=ops_dir)
    summary = run_independent_review_summary_drill(ops_dir=ops_dir)
    blockers = run_remaining_blockers_drill(ops_dir=ops_dir)
    request = {
        "reviewer_action": "Complete docs/INDEPENDENT_REVIEW_CHECKLIST.md sign-off table",
        "summary_path": summary.get("summary_path"),
        "checklist": "docs/INDEPENDENT_REVIEW_CHECKLIST.md",
        "readiness_score": ready.get("score"),
        "artifact_count": pack.get("artifact_count"),
        "open_blockers": [
            {"id": row.get("id"), "gate": row.get("gate"), "label": row.get("label")}
            for row in (blockers.get("blockers") or [])
        ],
        "note": "Agent-generated request only; independent human reviewer required",
    }
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_request",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "signed_off": False,
        "request": request,
        "ok": (
            bool(ready.get("ok"))
            and pack.get("signed_off") is False
            and summary.get("signed_off") is False
        ),
        "reason": (
            f"Independent review request receipt prepared "
            f"({pack.get('artifact_count')} artifacts, "
            f"{blockers.get('open_count')} blockers); human sign-off still pending"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "independent_review_request_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_request_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
