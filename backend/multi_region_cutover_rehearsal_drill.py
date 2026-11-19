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


def run_multi_region_cutover_rehearsal_drill(*, ops_dir: Path | None = None) -> dict:
    from .failover_rto_drill import run_failover_rto_drill
    from .minio_multi_region_drill import run_minio_multi_region_drill
    from .multi_region_dr_drill import run_multi_region_dr_drill
    from .multi_store_dr_drill import run_multi_store_dr_drill
    from .redis_multi_region_drill import run_redis_multi_region_drill

    started = time.perf_counter()
    steps = {
        "postgres_dual_region": run_multi_region_dr_drill(ops_dir=ops_dir),
        "minio_dual_bucket": run_minio_multi_region_drill(ops_dir=ops_dir),
        "redis_dual_db": run_redis_multi_region_drill(ops_dir=ops_dir),
        "multi_store_pack": run_multi_store_dr_drill(ops_dir=ops_dir),
        "failover_rto": run_failover_rto_drill(ops_dir=ops_dir),
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
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "multi_region_cutover_rehearsal_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "multi_region_cutover_rehearsal_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
