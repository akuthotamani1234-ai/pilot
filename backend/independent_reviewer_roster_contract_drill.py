"""Gate G: independent reviewer roster contract (unsigned).

Records expected reviewer roles and coverage before sign-off. Does **not**
collect a signature — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_reviewer_roster_contract_drill.json"

LOCAL_PARTIAL = (
    "independent_review_request_drill.json",
    "independent_review_scope_matrix_drill.json",
    "independent_review_handoff_pack_drill.json",
    "independent_review_response_sla_drill.json",
    "independent_review_attestation_drill.json",
    "INDEPENDENT_REVIEW_SUMMARY.md",
)

ROLES = (
    {"role": "security", "gates": ["G", "I", "H"], "required": True},
    {"role": "reliability", "gates": ["A", "E", "H"], "required": True},
    {"role": "platform_ci", "gates": ["D", "F"], "required": True},
    {"role": "product_qa", "gates": ["B", "C", "J"], "required": False},
)


def _linked_roster() -> dict:
    return {
        "gate_g_complete": False,
        "ok": False,
        "drill": "independent_reviewer_roster_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_reviewer_roster_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "independent_reviewer_roster_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_roster()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    signed_off = False
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_reviewer_roster_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "unsigned_roster_contract",
        "roles": list(ROLES),
        "assignees": [],
        "signed_off": signed_off,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL) and signed_off is False,
        "reason": (
            f"Independent reviewer roster contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "external sign-off still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_roster()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_roster()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
