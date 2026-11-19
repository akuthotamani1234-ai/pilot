"""Gate H: multi-region cutover rehearsal pack (local stores only).

Runs Postgres dual-region + MinIO dual-bucket + Redis dual-DB + failover RTO
as one cutover pack with a measured wall-clock. Hosted multi-region DR /
on-call still open — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "multi_region_cutover_rehearsal_drill.json"


def _safe_step(name: str, runner) -> dict:
    try:
        result = runner()
        if isinstance(result, dict):
            return result
        return {"ok": False, "drill": name, "reason": "step returned non-dict"}
    except Exception as exc:
        return {
            "ok": False,
            "drill": name,
            "gate_h_complete": False,
            "reason": f"{name} unavailable: {exc}; hosted multi-region DR still open",
        }


def _linked_rehearsal() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "multi_region_cutover_rehearsal",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_multi_region_cutover_rehearsal_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "multi_region_cutover_rehearsal_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_rehearsal()

    from .failover_rto_drill import run_failover_rto_drill
    from .minio_multi_region_drill import run_minio_multi_region_drill
    from .multi_region_dr_drill import run_multi_region_dr_drill
    from .multi_store_dr_drill import run_multi_store_dr_drill
    from .redis_multi_region_drill import run_redis_multi_region_drill

    started = time.perf_counter()
    steps = {
        "postgres_dual_region": _safe_step(
            "postgres_dual_region",
            lambda: run_multi_region_dr_drill(ops_dir=ops_dir),
        ),
        "minio_dual_bucket": _safe_step(
            "minio_dual_bucket",
            lambda: run_minio_multi_region_drill(ops_dir=ops_dir),
        ),
        "redis_dual_db": _safe_step(
            "redis_dual_db",
            lambda: run_redis_multi_region_drill(ops_dir=ops_dir),
        ),
        "multi_store_pack": _safe_step(
            "multi_store_pack",
            lambda: run_multi_store_dr_drill(ops_dir=ops_dir),
        ),
        "failover_rto": _safe_step(
            "failover_rto",
            lambda: run_failover_rto_drill(ops_dir=ops_dir),
        ),
    }
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    passed = {name: bool(ev.get("ok")) for name, ev in steps.items()}
    evidence = {
        "gate_h_complete": False,
        "drill": "multi_region_cutover_rehearsal",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_cutover_pack",
        "steps_ok": passed,
        "steps_passed": sum(1 for ok in passed.values() if ok),
        "steps_total": len(passed),
        "elapsed_ms": elapsed_ms,
        "ok": all(passed.values()),
        "reason": (
            f"Local multi-region cutover rehearsal "
            f"{sum(1 for ok in passed.values() if ok)}/{len(passed)} "
            f"in {elapsed_ms}ms; hosted multi-region DR / on-call still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_rehearsal()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_rehearsal()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
