"""Gate G: unsigned independent-review attestation stub.

Produces a reviewer-facing attestation template bound to the evidence catalog
integrity hash. Does **not** collect a human signature —
``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_attestation_drill.json"


def _linked_attestation() -> dict:
    return {
        "gate_g_complete": False,
        "ok": False,
        "signed_off": False,
        "drill": "independent_review_attestation",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_review_attestation_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    from .independent_review_evidence_catalog_drill import (
        run_independent_review_evidence_catalog_drill,
    )
    from .independent_review_integrity_drill import (
        run_independent_review_integrity_drill,
    )

    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_attestation()
    catalog = run_independent_review_evidence_catalog_drill(ops_dir=ops_dir)
    integrity = run_independent_review_integrity_drill(ops_dir=ops_dir)
    attestation = {
        "title": "Qpilot X Independent Review Attestation",
        "scope": "Gates A–J evidence pack for security/reliability review",
        "integrity_sha256": integrity.get("integrity_sha256"),
        "catalog_entries": int(catalog.get("entry_count") or 0),
        "reviewer_name": "",
        "reviewer_org": "",
        "signed_at": "",
        "signature": "",
        "verdict": "pending",
        "notes": (
            "Fill reviewer fields and attach signature out-of-band. "
            "Local unsigned stub does not close Gate G."
        ),
    }
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_attestation",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "signed_off": False,
        "attestation": attestation,
        "catalog_ok": bool(catalog.get("ok")),
        "integrity_ok": bool(integrity.get("ok")),
        "ok": (
            bool(catalog.get("ok"))
            and bool(integrity.get("ok"))
            and not attestation["signature"]
            and attestation["verdict"] == "pending"
        ),
        "reason": (
            "Independent review attestation stub ready (unsigned); "
            "external sign-off still open"
            if catalog.get("ok") and integrity.get("ok")
            else "Attestation stub incomplete; independent sign-off still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out = (
        (Path(ops_dir) / "independent_review_attestation_drill.json")
        if ops_dir else EVIDENCE
    )
    if folder_is_linked(dest) or folder_is_linked(out):
        return _linked_attestation()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out.name, json.dumps(evidence, indent=2)):
        return _linked_attestation()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_attestation_drill.json"
        md = ROOT / "docs" / "ops-evidence" / "INDEPENDENT_REVIEW_ATTESTATION.md"
        note = (
            "# Independent Review Attestation (unsigned)\n\n"
            f"- Integrity: `{attestation['integrity_sha256']}`\n"
            f"- Catalog entries: {attestation['catalog_entries']}\n"
            f"- Verdict: **{attestation['verdict']}**\n"
            f"- Reviewer: _(pending)_\n"
            f"- Signed at: _(pending)_\n\n"
            f"{attestation['notes']}\n"
        )
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
        if not folder_is_linked(md) and not folder_is_linked(md.parent):
            write_text_unless_linked(md.parent, md.name, note)
    return evidence
