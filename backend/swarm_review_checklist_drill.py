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


def _linked_checklist() -> dict:
    return {
        "gate_b_complete": False,
        "ok": False,
        "drill": "swarm_product_review_checklist",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_swarm_review_checklist_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "swarm_review_checklist.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_checklist()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        name for name in POINTERS
        if not folder_is_linked(ops / name) and (ops / name).is_file()
    ]
    evidence = {
        "gate_b_complete": False,
        "drill": "swarm_product_review_checklist",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checklist": "docs/SWARM_PRODUCT_REVIEW_CHECKLIST.md",
        "checklist_present": (not folder_is_linked(CHECKLIST)) and CHECKLIST.is_file(),
        "signed_off": False,
        "evidence_pointers_present": present,
        "evidence_pointers_missing": [n for n in POINTERS if n not in present],
        "ok": (
            (not folder_is_linked(CHECKLIST))
            and CHECKLIST.is_file()
            and len(present) >= 4
        ),
        "reason": (
            f"Swarm product review checklist published ({len(present)}/{len(POINTERS)} "
            "evidence pointers); independent sign-off still pending"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_checklist()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_checklist()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
