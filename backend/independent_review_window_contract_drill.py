"""Gate G: independent review window / embargo contract (unsigned).

Records expected review window length and evidence freeze rules. Does **not**
collect a signature — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_window_contract_drill.json"

LOCAL_PARTIAL = (
    "independent_review_request_drill.json",
    "independent_review_response_sla_drill.json",
    "independent_review_blocker_freeze_drill.json",
    "independent_review_findings_freeze_drill.json",
    "independent_reviewer_roster_contract_drill.json",
    "independent_review_handoff_pack_drill.json",
)


def _linked_window() -> dict:
    return {
        "gate_g_complete": False,
        "ok": False,
        "drill": "independent_review_window_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_review_window_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "independent_review_window_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_window()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    signed_off = False
    window = {
        "business_days": 10,
        "evidence_freeze_required": True,
        "allow_hotfix_exceptions": True,
        "embargo_until_signoff": True,
        "note": "Window contract only; external sign-off still required",
    }
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_window_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "unsigned_window_contract",
        "window": window,
        "signed_off": signed_off,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL) and signed_off is False,
        "reason": (
            f"Independent review window contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "external sign-off still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_window()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_window()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
