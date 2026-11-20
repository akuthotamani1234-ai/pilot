"""Gate G: independent review response SLA contract (unsigned).

Records expected reviewer ack/response windows and required deliverables.
Does **not** collect a signature — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_response_sla_drill.json"

LOCAL_PARTIAL = (
    "independent_review_checklist.json",
    "independent_review_pack.json",
    "independent_review_readiness_drill.json",
    "independent_review_request_drill.json",
    "independent_review_handoff_pack_drill.json",
    "independent_review_scope_matrix_drill.json",
    "independent_review_blocker_freeze_drill.json",
    "INDEPENDENT_REVIEW_SUMMARY.md",
    "INDEPENDENT_REVIEW_FINDINGS.md",
)


def _linked_sla() -> dict:
    return {
        "gate_g_complete": False,
        "ok": False,
        "drill": "independent_review_response_sla",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_review_response_sla_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "independent_review_response_sla_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_sla()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    sla = {
        "ack_business_days": 2,
        "first_findings_business_days": 5,
        "signoff_business_days": 10,
        "required_deliverables": [
            "findings_markdown",
            "attestation_signature",
            "blocker_freeze_ack",
        ],
        "channels": ["email", "ticket"],
        "note": "Response SLA contract only; external sign-off still required",
    }
    signed_off = False
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_response_sla",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "unsigned_sla_contract",
        "sla": sla,
        "signed_off": signed_off,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL) and signed_off is False,
        "reason": (
            f"Independent review response SLA recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "external sign-off still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_sla()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_sla()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
