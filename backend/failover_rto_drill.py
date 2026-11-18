"""Gate H: local multi-store failover RTO measurement pack.

Times Postgres dual-region, MinIO dual-bucket, and Redis dual-DB failovers and
records restore RTO against a local budget. Hosted multi-region DR / on-call
still open — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "failover_rto_drill.json"

# Local rehearsal budget only — not a production SLO claim.
LOCAL_RTO_BUDGET_MS = 120_000


def _time_store(name: str, runner) -> dict:
    t0 = time.perf_counter()
    try:
        result = runner()
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "store": name,
            "ok": bool(result.get("ok")),
            "elapsed_ms": elapsed_ms,
            "within_budget": elapsed_ms <= LOCAL_RTO_BUDGET_MS,
            "reason": (result.get("reason") or "")[:160],
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "store": name,
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "within_budget": False,
            "reason": str(exc)[:160],
        }


def run_failover_rto_drill(*, ops_dir: Path | None = None) -> dict:
    from .minio_multi_region_drill import run_minio_multi_region_drill
    from .multi_region_dr_drill import run_multi_region_dr_drill
    from .redis_multi_region_drill import run_redis_multi_region_drill

    rows = [
        _time_store("postgres", lambda: run_multi_region_dr_drill(ops_dir=ops_dir)),
        _time_store("minio", lambda: run_minio_multi_region_drill(ops_dir=ops_dir)),
        _time_store("redis", lambda: run_redis_multi_region_drill(ops_dir=ops_dir)),
    ]
    passed = sum(1 for r in rows if r.get("ok") and r.get("within_budget"))
    total_ms = sum(int(r.get("elapsed_ms") or 0) for r in rows)
    evidence = {
        "gate_h_complete": False,
        "drill": "failover_rto",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "local_rto_budget_ms": LOCAL_RTO_BUDGET_MS,
        "stores": rows,
        "passed": passed,
        "total": len(rows),
        "total_elapsed_ms": total_ms,
        "ok": passed == len(rows),
        "reason": (
            f"Local failover RTO {passed}/{len(rows)} stores "
            f"(budget={LOCAL_RTO_BUDGET_MS}ms, total={total_ms}ms); "
            "hosted multi-region DR / on-call still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "failover_rto_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "failover_rto_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
