"""Gate B: Redis DurableQueue multi-worker lease contention drill.

Enqueues several tasks and has two workers claim without double-claiming.
Product-wide swarm review still open — ``gate_b_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .queue_backend import open_durable_queue
from .swarm_protocol import new_task

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "redis_swarm_contention_drill.json"


def _linked_swarm() -> dict:
    return {
        "gate_b_complete": False,
        "ok": False,
        "drill": "redis_swarm_contention",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_redis_swarm_contention_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / "redis_swarm_contention_drill.json"):
        return _linked_swarm()

    rid = f"swarm-contention-{int(time.time())}"
    db_parent = ROOT / "artifacts" / "ops"
    db_path = db_parent / f"{rid}.sqlite"
    if folder_is_linked(db_parent) or folder_is_linked(db_path):
        return _linked_swarm()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    opened = open_durable_queue(default_path=db_path)
    if not opened.get("ready") or opened.get("queue") is None:
        opened = open_durable_queue("sqlite:" + str(db_path), default_path=db_path)
    queue = opened["queue"]
    backend = opened.get("backend") or "sqlite"
    if queue is None:
        evidence = {
            "gate_b_complete": False,
            "drill": "redis_swarm_contention",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "backend": backend,
            "reason": opened.get("reason") or "durable queue unavailable",
        }
        if not _write(evidence, ops_dir):
            return _linked_swarm()
        return evidence

    for i in range(4):
        task = new_task(
            role="worker",
            url=f"http://127.0.0.1/demo/{i}",
            status="partial",
            reason="contention-drill",
            action_budget=3,
            time_budget_s=20,
        )
        queue.enqueue(
            run_id=rid,
            role="worker",
            payload=task,
            idempotency_key=f"{rid}:{task['task_id']}",
        )

    claimed_a = []
    claimed_b = []
    for _ in range(4):
        a = queue.claim(worker_id="worker-a", run_id=rid)
        if a:
            claimed_a.append(a["task_id"])
        b = queue.claim(worker_id="worker-b", run_id=rid)
        if b:
            claimed_b.append(b["task_id"])

    overlap = set(claimed_a) & set(claimed_b)
    total_claimed = len(claimed_a) + len(claimed_b)
    ok = (
        backend == "redis"
        and total_claimed >= 4
        and not overlap
        and len(set(claimed_a + claimed_b)) == total_claimed
    )
    evidence = {
        "gate_b_complete": False,
        "drill": "redis_swarm_contention",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backend": backend,
        "redis_url_set": bool(os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL")),
        "run_id": rid,
        "claimed_a": claimed_a,
        "claimed_b": claimed_b,
        "overlap": list(overlap),
        "total_claimed": total_claimed,
        "ok": ok,
        "reason": (
            f"Redis swarm contention: workers claimed {total_claimed} distinct tasks "
            f"(a={len(claimed_a)}, b={len(claimed_b)}, overlap={len(overlap)}); "
            "product-wide review still open"
            if ok else
            f"Swarm contention drill incomplete (backend={backend}, claimed={total_claimed}, "
            f"overlap={len(overlap)}); product-wide review still open"
        ),
    }
    if not _write(evidence, ops_dir):
        return _linked_swarm()
    return evidence


def _write(evidence: dict, ops_dir: Path | None) -> bool:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "redis_swarm_contention_drill.json"
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return False
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return False
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return True
