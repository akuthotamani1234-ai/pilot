"""Gate H: multi-region DR readiness pack (local stores + cutover + on-call).

Bundles multi-store DR, failover RTO, cutover rehearsal, and on-call pack.
Does **not** prove hosted multi-region DR — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "multi_region_dr_readiness_pack_drill.json"


def _linked_pack() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "multi_region_dr_readiness_pack",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_multi_region_dr_readiness_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "multi_region_dr_readiness_pack_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_pack()

    from .failover_rto_drill import run_failover_rto_drill
    from .hosted_oncall_readiness_pack_drill import (
        run_hosted_oncall_readiness_pack_drill,
    )
    from .multi_region_cutover_rehearsal_drill import (
        run_multi_region_cutover_rehearsal_drill,
    )
    from .multi_store_dr_drill import run_multi_store_dr_drill

    started = time.perf_counter()
    parts = {}
    for key, fn in (
        ("multi_store", run_multi_store_dr_drill),
        ("failover_rto", run_failover_rto_drill),
        ("cutover", run_multi_region_cutover_rehearsal_drill),
        ("oncall_pack", run_hosted_oncall_readiness_pack_drill),
    ):
        try:
            parts[key] = fn(ops_dir=ops_dir)
        except Exception as exc:
            parts[key] = {"ok": False, "reason": str(exc)[:160]}
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ok = all(bool((parts.get(k) or {}).get("ok")) for k in parts)
    evidence = {
        "gate_h_complete": False,
        "drill": "multi_region_dr_readiness_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_ops_pack",
        "parts": {k: bool((v or {}).get("ok")) for k, v in parts.items()},
        "live_hosted_dr": False,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "reason": (
            f"Multi-region DR readiness pack ok in {elapsed_ms}ms; "
            "live hosted multi-region DR / on-call still open"
            if ok else
            "Multi-region DR readiness pack incomplete; hosted DR still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_pack()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_pack()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
