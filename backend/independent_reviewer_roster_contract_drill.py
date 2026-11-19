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


def run_independent_reviewer_roster_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
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
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "independent_reviewer_roster_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = (
            ROOT / "artifacts" / "ops" / "independent_reviewer_roster_contract_drill.json"
        )
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
