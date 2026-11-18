"""Gate H: combined multi-store DR failover rehearsal (local).

Runs Postgres dual-region, MinIO dual-bucket, and Redis dual-DB failovers in
one evidence pack. Hosted multi-region DR / on-call still open —
``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "multi_store_dr_drill.json"


def run_multi_store_dr_drill(*, ops_dir: Path | None = None) -> dict:
    from .minio_multi_region_drill import run_minio_multi_region_drill
    from .multi_region_dr_drill import run_multi_region_dr_drill
    from .redis_multi_region_drill import run_redis_multi_region_drill

    # Isolate child evidence when ops_dir provided so tests stay clean.
    pg = run_multi_region_dr_drill(ops_dir=ops_dir)
    minio = run_minio_multi_region_drill(ops_dir=ops_dir)
    redis = run_redis_multi_region_drill(ops_dir=ops_dir)
    stores = {
        "postgres": {
            "ok": bool(pg.get("ok")),
            "reason": (pg.get("reason") or "")[:160],
            "region_a": pg.get("region_a"),
            "region_b": pg.get("region_b"),
        },
        "minio": {
            "ok": bool(minio.get("ok")),
            "reason": (minio.get("reason") or "")[:160],
            "region_a": minio.get("region_a"),
            "region_b": minio.get("region_b"),
        },
        "redis": {
            "ok": bool(redis.get("ok")),
            "reason": (redis.get("reason") or "")[:160],
            "region_a_db": redis.get("region_a_db"),
            "region_b_db": redis.get("region_b_db"),
        },
    }
    # Require each store that is available to pass; skip-not-configured counts
    # as not ok unless the reason clearly says URL unset (still Partial).
    passed = sum(1 for s in stores.values() if s["ok"])
    evidence = {
        "gate_h_complete": False,
        "drill": "multi_store_dr_failover",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stores": stores,
        "passed": passed,
        "total": 3,
        "ok": passed == 3,
        "reason": (
            f"Local multi-store DR failover {passed}/3 "
            "(Postgres + MinIO + Redis); hosted multi-region DR / on-call still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "multi_store_dr_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "multi_store_dr_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
