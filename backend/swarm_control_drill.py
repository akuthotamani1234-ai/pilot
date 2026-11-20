"""Gate B: swarm cancel / checkpoint / budget evidence drill.

Exercises DurableQueue lease → checkpoint → cancel (Redis when REDIS_URL set,
else SQLite). Product-wide review still open — gate_b_complete stays False.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .queue_backend import open_durable_queue
from .swarm_protocol import new_task

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "swarm_control_drill.json"


def _linked_control() -> dict:
    return {
        "gate_b_complete": False,
        "ok": False,
        "drill": "swarm_cancel_checkpoint_budget",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_swarm_control_drill(*, ops_dir: Path | None = None, run_id: str | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "swarm_control_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_control()

    rid = run_id or f"swarm-control-{int(time.time())}"
    # Prefer REDIS_URL when set (same policy as swarm supervisor).
    db_parent = ROOT / "artifacts" / "ops"
    db_path = db_parent / f"{rid}.sqlite"
    if folder_is_linked(db_parent) or folder_is_linked(db_path):
        return _linked_control()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    opened = open_durable_queue(default_path=db_path)
    if not opened.get("ready") or opened.get("queue") is None:
        opened = open_durable_queue("sqlite:" + str(db_path), default_path=db_path)
    queue = opened["queue"]
    backend = opened.get("backend") or "sqlite"
    if queue is None:
        return {
            "gate_b_complete": False,
            "drill": "swarm_cancel_checkpoint_budget",
            "ok": False,
            "reason": opened.get("reason") or "durable queue unavailable",
            "backend": backend,
        }

    task = new_task(
        role="worker",
        url="http://127.0.0.1/demo",
        status="partial",
        reason="control-drill",
        action_budget=5,
        time_budget_s=30,
    )
    row = queue.enqueue(
        run_id=rid,
        role="worker",
        payload=task,
        idempotency_key=f"{rid}:{task['task_id']}",
    )
    claimed = queue.claim(worker_id="drill-worker", run_id=rid)
    checkpointed = False
    if claimed and hasattr(queue, "checkpoint"):
        checkpointed = bool(queue.checkpoint(claimed["task_id"], "drill-worker", {
            "step": "opened",
            "budget_remaining": 4,
        }))
    cancelled = False
    if claimed and hasattr(queue, "cancel"):
        cancelled = bool(queue.cancel(claimed["task_id"]))
    after = queue.get(claimed["task_id"]) if claimed else None
    status = (after or {}).get("status") if isinstance(after, dict) else None

    evidence = {
        "gate_b_complete": False,
        "drill": "swarm_cancel_checkpoint_budget",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backend": backend,
        "redis_url_set": bool(os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL")),
        "run_id": rid,
        "task_id": (claimed or row or {}).get("task_id"),
        "action_budget": task.get("action_budget"),
        "time_budget_s": task.get("time_budget_s"),
        "claimed": bool(claimed),
        "checkpointed": checkpointed,
        "cancelled": cancelled,
        "final_status": status,
        "ok": bool(claimed and checkpointed and cancelled and status == "cancelled"),
        "reason": (
            f"Swarm control drill on {backend}: claim/checkpoint/cancel exercised; "
            "product-wide durable supervisor review still open"
        ),
    }

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_control()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_control()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
