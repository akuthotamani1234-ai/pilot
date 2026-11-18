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
OUT = EVIDENCE_DIR / "independent_review_pack.json"
CHECKLIST = ROOT / "docs" / "INDEPENDENT_REVIEW_CHECKLIST.md"


def run_independent_review_pack_drill(*, ops_dir: Path | None = None) -> dict:
    files: list[dict] = []
    for path in sorted(EVIDENCE_DIR.glob("*.json")):
        if path.name == "independent_review_pack.json":
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
    dest = Path(ops_dir) if ops_dir else EVIDENCE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "independent_review_pack.json") if ops_dir else OUT
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_pack.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
