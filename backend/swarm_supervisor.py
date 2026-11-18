"""Minimal durable supervisor for Gate B local mode.

Builds typed tasks from a URL partition, enqueues them idempotently, and drives
claim → work → complete/fail until the run drains or is cancelled.
"""
from __future__ import annotations

from pathlib import Path

from .queue_backend import open_durable_queue
from .swarm import is_payment_url, partition_site
from .swarm_protocol import new_task, validate_task
from .swarm_queue import DurableQueue


def plan_run(run_id: str, urls: list[str], *, worker_count: int = 2, limit: int | None = None) -> list[dict]:
    """Create leader + worker task envelopes for safe URLs only."""
    assignments = partition_site(urls, worker_count, limit=limit)
    leader = new_task(role="leader", url=urls[0] if urls else "", scope="site",
                      status="completed", evidence=[f"planned {len(assignments)} worker page(s)"])
    tasks = [leader]
    for row in assignments:
        url = row["url"]
        if is_payment_url(url):
            continue
        tasks.append(new_task(
            role="worker", url=url, parent_task_id=leader["task_id"],
            worker=row["worker"], status="partial", reason="scheduled",
        ))
    return tasks


def enqueue_plan(queue: DurableQueue, run_id: str, tasks: list[dict]) -> list[dict]:
    """Persist planned tasks. Validation failures are stored as blocked."""
    stored = []
    for task in tasks:
        problems = validate_task(task)
        payload = dict(task)
        if problems:
            payload["blocked_reasons"] = problems
        role = task.get("role") or "worker"
        row = queue.enqueue(
            run_id=run_id,
            role=role,
            payload=payload,
            idempotency_key=f"{run_id}:{task.get('task_id') or payload.get('url')}",
        )
        if problems or task.get("status") == "blocked":
            queue.mark_blocked(row["task_id"], "; ".join(problems) if problems else task.get("reason") or "blocked")
            row = queue.get(row["task_id"])
        stored.append(row)
    return stored


def drain(queue: DurableQueue, *, run_id: str, worker_id: str, work) -> dict:
    """Claim and process pending tasks until none remain for this run.

    ``work(task) -> dict`` must return a result envelope. Raise with ``error_class``
    attribute for classified failures, or return {"error_class": "..."}.
    """
    processed = 0
    while True:
        task = queue.claim(worker_id=worker_id, run_id=run_id)
        if not task:
            break
        if task["payload"].get("status") == "completed" and task["role"] == "leader":
            queue.complete(task["task_id"], worker_id, {"evidence": task["payload"].get("evidence") or []})
            processed += 1
            continue
        try:
            result = work(task)
            if isinstance(result, dict) and result.get("error_class"):
                queue.fail(task["task_id"], worker_id, error_class=result["error_class"],
                          detail=str(result.get("detail") or ""))
            else:
                queue.complete(task["task_id"], worker_id, result if isinstance(result, dict) else {"ok": True})
        except Exception as exc:
            error_class = getattr(exc, "error_class", "worker_crash")
            queue.fail(task["task_id"], worker_id, error_class=str(error_class), detail=str(exc))
        processed += 1
    return {"processed": processed, "tasks": queue.list_run(run_id)}


def open_queue(run_dir: str | Path, **kwargs) -> DurableQueue:
    """Queue file for one run directory (local SQLite via the backend selector)."""
    opened = open_durable_queue(f"sqlite:{Path(run_dir) / 'swarm_queue.sqlite'}", **kwargs)
    if not opened.get("ready") or opened.get("queue") is None:
        raise RuntimeError(opened.get("reason") or "durable queue is not ready")
    return opened["queue"]
