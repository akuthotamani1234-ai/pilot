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


def run_independent_review_findings_freeze_drill(*, ops_dir: Path | None = None) -> dict:
    from .independent_review_blocker_freeze_drill import (
        run_independent_review_blocker_freeze_drill,
    )

    freeze = run_independent_review_blocker_freeze_drill(ops_dir=ops_dir)
    findings_text = FINDINGS.read_text(encoding="utf-8") if FINDINGS.is_file() else ""
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
        "findings_present": FINDINGS.is_file(),
        "signed_off": signed_off,
        "ok": (
            FINDINGS.is_file()
            and bool(freeze.get("ok"))
            and signed_off is False
        ),
        "reason": (
            f"Findings freeze {digest[:12]}… (unsigned); "
            "external sign-off still open"
            if FINDINGS.is_file() and freeze.get("ok") else
            "Findings freeze incomplete; independent sign-off still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "independent_review_findings_freeze_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = (
            ROOT / "artifacts" / "ops" / "independent_review_findings_freeze_drill.json"
        )
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
