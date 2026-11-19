"""Gate G: independent-review evidence integrity checksum (unsigned).

Hashes checklist + pack + readiness + summary + request + blockers into one
integrity receipt for reviewers. Does **not** sign off —
``signed_off`` stays False.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_integrity_drill.json"

ARTIFACTS = (
    "docs/INDEPENDENT_REVIEW_CHECKLIST.md",
    "docs/ops-evidence/independent_review_pack.json",
    "docs/ops-evidence/independent_review_readiness_drill.json",
    "docs/ops-evidence/independent_review_summary_drill.json",
    "docs/ops-evidence/INDEPENDENT_REVIEW_SUMMARY.md",
    "docs/ops-evidence/independent_review_request_drill.json",
    "docs/ops-evidence/remaining_blockers.json",
)


def _linked_drill() -> dict:
    return {
        "gate_g_complete": False,
        "ok": False,
        "signed_off": False,
        "drill": "independent_review_integrity",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_independent_review_integrity_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    from .independent_review_request_drill import run_independent_review_request_drill

    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_drill()
    # Refresh request/pack/readiness/summary chain first.
    request = run_independent_review_request_drill(ops_dir=ops_dir)
    rows = []
    missing = []
    for rel in ARTIFACTS:
        path = ROOT / rel
        if ops_dir is not None and rel.startswith("docs/ops-evidence/"):
            path = Path(ops_dir) / Path(rel).name
        if folder_is_linked(path):
            return _linked_drill()
        if not path.is_file():
            missing.append(rel)
            continue
        raw = path.read_bytes()
        rows.append({
            "path": rel,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    digest_body = json.dumps(rows, sort_keys=True).encode("utf-8")
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_integrity",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "signed_off": False,
        "artifacts": rows,
        "missing": missing,
        "integrity_sha256": hashlib.sha256(digest_body).hexdigest(),
        "request_ok": bool(request.get("ok")),
        "ok": not missing and request.get("signed_off") is False and bool(request.get("ok")),
        "reason": (
            f"Independent review integrity over {len(rows)} artifacts; "
            "human sign-off still pending"
            if not missing else
            f"Independent review integrity missing {len(missing)} artifacts; "
            "human sign-off still pending"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out = (
        (Path(ops_dir) / "independent_review_integrity_drill.json")
        if ops_dir else EVIDENCE
    )
    if folder_is_linked(dest) or folder_is_linked(out):
        return _linked_drill()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out.name, json.dumps(evidence, indent=2)):
        return _linked_drill()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_integrity_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
