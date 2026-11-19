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


def run_independent_review_integrity_drill(*, ops_dir: Path | None = None) -> dict:
    from .independent_review_request_drill import run_independent_review_request_drill

    # Refresh request/pack/readiness/summary chain first.
    request = run_independent_review_request_drill(ops_dir=ops_dir)
    rows = []
    missing = []
    for rel in ARTIFACTS:
        path = ROOT / rel
        if ops_dir is not None and rel.startswith("docs/ops-evidence/"):
            path = Path(ops_dir) / Path(rel).name
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
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "independent_review_integrity_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_integrity_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
