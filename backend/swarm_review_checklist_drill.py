"""Gate B: product-wide swarm review checklist snapshot (unsigned).

Publishes the checklist path and confirms evidence pointers exist. Does not
sign off Gate B — ``signed_off`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "swarm_review_checklist.json"
CHECKLIST = ROOT / "docs" / "SWARM_PRODUCT_REVIEW_CHECKLIST.md"
POINTERS = (
    "redis_durable_queue_drill.json",
    "swarm_redis_default.json",
    "redis_lease_drill.json",
    "swarm_retry_drill.json",
    "swarm_control_drill.json",
    "redis_multi_region_drill.json",
)


def run_swarm_review_checklist_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [name for name in POINTERS if (ops / name).is_file()]
    evidence = {
        "gate_b_complete": False,
        "drill": "swarm_product_review_checklist",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checklist": "docs/SWARM_PRODUCT_REVIEW_CHECKLIST.md",
        "checklist_present": CHECKLIST.is_file(),
        "signed_off": False,
        "evidence_pointers_present": present,
        "evidence_pointers_missing": [n for n in POINTERS if n not in present],
        "ok": CHECKLIST.is_file() and len(present) >= 4,
        "reason": (
            f"Swarm product review checklist published ({len(present)}/{len(POINTERS)} "
            "evidence pointers); independent sign-off still pending"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "swarm_review_checklist.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "swarm_review_checklist.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
