"""Gate B: lease-expiry → retry_wait control drill.

Forces an expired lease and recovers into retry_wait (Redis when REDIS_URL
set, else SQLite). Product-wide review still open — gate_b_complete stays False.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .queue_backend import open_durable_queue
from .swarm_protocol import new_task

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "swarm_retry_drill.json"


def _force_lease_expired(queue, task_id: str) -> bool:
    """Backdate lease_until so recover_expired will requeue the task."""
    past = time.time() - 5
    db = getattr(queue, "_db", None)
    if db is not None:
        db.execute("UPDATE tasks SET lease_until=? WHERE task_id=? AND status='leased'", (past, task_id))
        db.commit()
        return True
    load = getattr(queue, "_load", None)
    dump = getattr(queue, "_dump", None)
    if callable(load) and callable(dump):
        row = load(task_id)
        if not row or row.get("status") != "leased":
            return False
        row["lease_until"] = past
        dump(row)
        return True
    return False


def run_swarm_retry_drill(*, ops_dir: Path | None = None, run_id: str | None = None) -> dict:
    rid = run_id or f"swarm-retry-{int(time.time())}"
    db_path = ROOT / "artifacts" / "ops" / f"{rid}.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    opened = open_durable_queue(default_path=db_path, lease_seconds=30, max_attempts=3)
    if not opened.get("ready") or opened.get("queue") is None:
        opened = open_durable_queue("sqlite:" + str(db_path), default_path=db_path,
                                   lease_seconds=30, max_attempts=3)
    queue = opened["queue"]
    backend = opened.get("backend") or "sqlite"
    if queue is None:
        return {
            "gate_b_complete": False,
            "drill": "swarm_lease_expiry_retry",
            "ok": False,
            "reason": opened.get("reason") or "durable queue unavailable",
            "backend": backend,
        }

    task = new_task(
        role="worker",
        url="http://127.0.0.1/demo-retry",
        status="partial",
        reason="retry-drill",
        action_budget=3,
        time_budget_s=20,
    )
    row = queue.enqueue(
        run_id=rid,
        role="worker",
        payload=task,
        idempotency_key=f"{rid}:{task['task_id']}",
    )
    claimed = queue.claim(worker_id="retry-worker-1", run_id=rid)
    task_id = (claimed or row or {}).get("task_id")
    forced = bool(claimed and task_id and _force_lease_expired(queue, task_id))
    recovered = queue.recover_expired() if forced else []
    after = queue.get(task_id) if task_id else None
    status = (after or {}).get("status") if isinstance(after, dict) else None
    error_class = (after or {}).get("error_class") if isinstance(after, dict) else None
    reclaimed = None
    if status == "retry_wait":
        reclaimed = queue.claim(worker_id="retry-worker-2", run_id=rid)

    evidence = {
        "gate_b_complete": False,
        "drill": "swarm_lease_expiry_retry",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backend": backend,
        "redis_url_set": bool(os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL")),
        "run_id": rid,
        "task_id": task_id,
        "claimed": bool(claimed),
        "lease_forced_expired": forced,
        "recovered_ids": list(recovered or []),
        "status_after_recover": status,
        "error_class": error_class,
        "reclaimed": bool(reclaimed),
        "reclaim_attempt": (reclaimed or {}).get("attempt") if reclaimed else None,
        "ok": bool(
            claimed
            and forced
            and task_id in (recovered or [])
            and status == "retry_wait"
            and error_class == "lease_expired"
            and reclaimed
            and int((reclaimed or {}).get("attempt") or 0) >= 2
        ),
        "reason": (
            f"Swarm lease-expiry→retry_wait drill on {backend}; "
            "product-wide durable supervisor review still open"
        ),
    }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "swarm_retry_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "swarm_retry_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
