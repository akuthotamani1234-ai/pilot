"""Gate G: assemble an independent-review evidence pack (unsigned).

Hashes ``docs/ops-evidence/*.json`` so a human/independent reviewer can
verify the artifact set. Does **not** sign off Gate G — ``signed_off`` stays
False and ``gate_g_complete`` stays False.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "docs" / "ops-evidence"
CHECKLIST = ROOT / "docs" / "INDEPENDENT_REVIEW_CHECKLIST.md"


def _linked_drill() -> dict:
    return {
        "gate_g_complete": False,
        "ok": False,
        "signed_off": False,
        "drill": "independent_review_pack",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_review_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    out_name = "independent_review_pack.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE_DIR
    if folder_is_linked(dest) or folder_is_linked(dest / out_name) or folder_is_linked(EVIDENCE_DIR):
        return _linked_drill()
    files: list[dict] = []
    for path in sorted(EVIDENCE_DIR.glob("*.json")):
        if path.name == "independent_review_pack.json" or folder_is_linked(path):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append({
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": digest,
        })
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checklist": "docs/INDEPENDENT_REVIEW_CHECKLIST.md",
        "checklist_present": CHECKLIST.is_file(),
        "signed_off": False,
        "artifact_count": len(files),
        "artifacts": files,
        "ok": CHECKLIST.is_file() and len(files) > 0,
        "reason": (
            f"Evidence pack ready ({len(files)} artifacts hashed); "
            "independent human/reviewer sign-off still pending"
        ),
    }
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, json.dumps(evidence, indent=2)):
        return _linked_drill()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_pack.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
