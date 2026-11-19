"""Gate G: freeze findings template + blocker inventory for reviewers (unsigned).

Hashes findings markdown + blocker freeze so reviewers can detect drift.
Does **not** sign off — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_findings_freeze_drill.json"
FINDINGS = ROOT / "docs" / "ops-evidence" / "INDEPENDENT_REVIEW_FINDINGS.md"


def _linked_freeze() -> dict:
    return {
        "gate_g_complete": False,
        "signed_off": False,
        "ok": False,
        "drill": "independent_review_findings_freeze",
        "findings_present": False,
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_review_findings_freeze_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    name = "independent_review_findings_freeze_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_freeze()
    from .independent_review_blocker_freeze_drill import (
        run_independent_review_blocker_freeze_drill,
    )

    freeze = run_independent_review_blocker_freeze_drill(ops_dir=ops_dir)
    if folder_is_linked(FINDINGS):
        findings_text = ""
        findings_present = False
    else:
        findings_present = FINDINGS.is_file()
        findings_text = FINDINGS.read_text(encoding="utf-8") if findings_present else ""
    findings_sha = hashlib.sha256(findings_text.encode("utf-8")).hexdigest()
    combined = {
        "findings_sha256": findings_sha,
        "blocker_freeze_sha256": freeze.get("freeze_sha256"),
        "open_count": (freeze.get("freeze") or {}).get("open_count"),
    }
    digest = hashlib.sha256(
        json.dumps(combined, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    signed_off = False
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_findings_freeze",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "unsigned_findings_freeze",
        "combined": combined,
        "findings_freeze_sha256": digest,
        "findings_present": findings_present,
        "signed_off": signed_off,
        "ok": (
            findings_present
            and bool(freeze.get("ok"))
            and signed_off is False
        ),
        "reason": (
            f"Findings freeze {digest[:12]}… (unsigned); "
            "external sign-off still open"
            if findings_present and freeze.get("ok") else
            "Findings freeze incomplete; independent sign-off still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_freeze()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_freeze()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
