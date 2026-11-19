"""Gate G: independent-review readiness score (unsigned).

Cross-checks checklist presence, evidence pack hashes, and hard-open blocker
inventory. Never signs off — ``signed_off`` and ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_readiness_drill.json"
CHECKLIST = ROOT / "docs" / "INDEPENDENT_REVIEW_CHECKLIST.md"


def _linked_drill() -> dict:
    return {
        "gate_g_complete": False,
        "ok": False,
        "signed_off": False,
        "drill": "independent_review_readiness",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_review_readiness_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    out_name = "independent_review_readiness_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    from .independent_review_pack_drill import run_independent_review_pack_drill
    from .remaining_blockers_drill import run_remaining_blockers_drill

    pack = run_independent_review_pack_drill(ops_dir=ops_dir)
    blockers = run_remaining_blockers_drill(ops_dir=ops_dir)
    checks = {
        "checklist_present": (not folder_is_linked(CHECKLIST)) and CHECKLIST.is_file(),
        "pack_ok": bool(pack.get("ok")),
        "pack_unsigned": pack.get("signed_off") is False,
        "blockers_inventoried": int(blockers.get("open_count") or 0) >= 1,
        "pack_has_artifacts": int(pack.get("artifact_count") or 0) > 0,
    }
    score = sum(1 for ok in checks.values() if ok)
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_readiness",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "signed_off": False,
        "checks": checks,
        "score": score,
        "score_of": len(checks),
        "open_blockers": int(blockers.get("open_count") or 0),
        "artifact_count": int(pack.get("artifact_count") or 0),
        "ok": score == len(checks) and pack.get("signed_off") is False,
        "reason": (
            f"Independent review readiness {score}/{len(checks)} "
            f"(artifacts={pack.get('artifact_count')}, blockers="
            f"{blockers.get('open_count')}); human sign-off still pending"
        ),
    }
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, json.dumps(evidence, indent=2)):
        return _linked_drill()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_readiness_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
