"""Gate G: independent review evidence retention contract (unsigned).

Records how long review artifacts / freeze hashes must be retained.
Does **not** sign off — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = (
    ROOT / "docs" / "ops-evidence"
    / "independent_review_evidence_retention_contract_drill.json"
)

LOCAL_PARTIAL = (
    "independent_review_pack.json",
    "independent_review_integrity_drill.json",
    "independent_review_evidence_catalog_drill.json",
    "independent_review_blocker_freeze_drill.json",
    "independent_review_findings_freeze_drill.json",
    "independent_review_window_contract_drill.json",
)


def _linked_retention() -> dict:
    return {
        "gate_g_complete": False,
        "ok": False,
        "drill": "independent_review_evidence_retention_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_review_evidence_retention_contract_drill(
    *, ops_dir: Path | None = None,
) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "independent_review_evidence_retention_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_retention()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    contract = {
        "retention_days": 365,
        "immutable_freeze_hashes": True,
        "retain": [
            "independent_review_pack.json",
            "independent_review_integrity_drill.json",
            "independent_review_blocker_freeze_drill.json",
            "independent_review_findings_freeze_drill.json",
            "INDEPENDENT_REVIEW_SUMMARY.md",
            "INDEPENDENT_REVIEW_ATTESTATION.md",
            "INDEPENDENT_REVIEW_FINDINGS.md",
        ],
        "delete_after_days": None,
        "note": "Retention contract only; independent human sign-off still required",
    }
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_evidence_retention_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "signed_off": False,
        "contract": contract,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL) and contract["retention_days"] >= 90,
        "reason": (
            f"Independent review evidence retention contract recorded "
            f"({contract['retention_days']}d, {len(present)}/{len(LOCAL_PARTIAL)} "
            "local partials); signed_off remains False"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_retention()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_retention()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
