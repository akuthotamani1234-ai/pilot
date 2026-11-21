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

_PAYMENT_REFUSAL = "checkout, payment and placing an order are never tested"


def plan_run(run_id: str, urls: list[str], *, worker_count: int = 2, limit: int | None = None) -> list[dict]:
    """Create leader + worker + specialist (coverage/oracle) envelopes for safe URLs."""
    assignments = partition_site(urls, worker_count, limit=limit)
    home = urls[0] if urls else ""
    leader = new_task(role="leader", url=home, scope="site",
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
    # Gate B specialists: one coverage + one oracle task per planned site (SQLite path).
    safe = [u for u in urls if u and not is_payment_url(u)][: max(1, int(limit or 40))]
    tasks.append(new_task(
        role="coverage", url=home or (safe[0] if safe else "about:blank"),
        parent_task_id=leader["task_id"], status="partial",
        reason="verify listing coverage",
        evidence=[],
    ))
    tasks.append(new_task(
        role="oracle", url=home or (safe[0] if safe else "about:blank"),
        parent_task_id=leader["task_id"], status="partial",
        reason="bind approved assertion",
        evidence=[],
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


def _checkpoint_lands_on_payment(saved: dict) -> bool:
    """True when any resume address is checkout, including a landing after a safe URL."""
    for key in ("url", "final_url", "page", "href"):
        if is_payment_url(str(saved.get(key) or "")):
            return True
    return False


def _keep_checkpoint(queue: DurableQueue, task: dict, worker_id: str, result) -> None:
    """Store a worker's resume point before the attempt is acked or failed.

    The next claim of a retried task then carries that checkpoint. A resume
    point on checkout or payment is not stored, so the retry does not continue
    there. A safe requested URL does not keep a landing on checkout.
    """
    saved = result.get("checkpoint") if isinstance(result, dict) else getattr(result, "checkpoint", None)
    if not isinstance(saved, dict) or _checkpoint_lands_on_payment(saved):
        return
    queue.checkpoint(task["task_id"], worker_id, saved)


def drain(queue: DurableQueue, *, run_id: str, worker_id: str, work) -> dict:
    """Claim and process pending tasks until none remain for this run.

    ``work(task) -> dict`` must return a result envelope. Raise with ``error_class``
    attribute for classified failures, or return {"error_class": "..."}.
    A rejected ack (expired lease) stops this drain. The task stays leased so
    recovery can requeue it. A checkpoint on the result is stored before the
    ack, so the next claim of a retry resumes there. Gate B stays incomplete.
    """
    processed = 0
    lease_lost: list[str] = []
    while True:
        task = queue.claim(worker_id=worker_id, run_id=run_id)
        if not task:
            break
        payload = task.get("payload") or {}
        if is_payment_url(str(payload.get("url") or "")):
            ok, _reason = queue.fail(
                task["task_id"], worker_id,
                error_class="rule_violation", detail=_PAYMENT_REFUSAL,
            )
            if not ok:
                lease_lost.append(task["task_id"])
                break
            processed += 1
            continue
        if payload.get("status") == "completed" and task["role"] == "leader":
            ok, _reason = queue.complete(
                task["task_id"], worker_id,
                {"evidence": task["payload"].get("evidence") or []},
            )
        else:
            try:
                result = work(task)
                _keep_checkpoint(queue, task, worker_id, result)
                if isinstance(result, dict) and result.get("error_class"):
                    ok, _reason = queue.fail(
                        task["task_id"], worker_id,
                        error_class=str(result["error_class"]),
                        detail=str(result.get("detail") or ""),
                    )
                elif isinstance(result, dict) and result.get("ok") is False:
                    # A negative worker verdict is not a successful queue ack.
                    ok, _reason = queue.fail(
                        task["task_id"], worker_id,
                        error_class="worker_rejected",
                        detail=str(result.get("detail") or result.get("reason") or "worker returned ok=False"),
                    )
                else:
                    ok, _reason = queue.complete(
                        task["task_id"], worker_id,
                        result if isinstance(result, dict) else {"ok": True},
                    )
            except Exception as exc:
                _keep_checkpoint(queue, task, worker_id, exc)
                error_class = getattr(exc, "error_class", "worker_crash")
                ok, _reason = queue.fail(
                    task["task_id"], worker_id,
                    error_class=str(error_class), detail=str(exc),
                )
        if not ok:
            lease_lost.append(task["task_id"])
            break
        processed += 1
    return {
        "processed": processed,
        "lease_lost": lease_lost,
        "gate_b_complete": False,
        "tasks": queue.list_run(run_id),
    }


def queue_backend_name(queue) -> str:
    """sqlite | redis — for evidence notes (never invents readiness)."""
    name = getattr(queue, "backend", None)
    if isinstance(name, str) and name:
        return name
    return "redis" if queue.__class__.__name__.startswith("Redis") else "sqlite"


def open_queue(run_dir: str | Path, **kwargs) -> DurableQueue:
    """Prefer Redis when REDIS_URL is set; else per-run SQLite.

    Product-wide Redis default when configured. Falls back to SQLite if Redis is
    unready. Gate B still needs review before complete.
    """
    import os

    path = Path(run_dir)
    from .swarm_queue import queue_path_is_linked
    queue_file = path / "swarm_queue.sqlite"
    if queue_path_is_linked(path) or queue_path_is_linked(queue_file):
        raise RuntimeError("The swarm queue is a link.")
    path.mkdir(parents=True, exist_ok=True)
    redis_uri = (os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL") or "").strip()
    if redis_uri.startswith(("redis://", "rediss://")):
        try:
            from .redis_queue import RedisDurableQueue

            lease = int(kwargs.get("lease_seconds") or 90)
            attempts = int(kwargs.get("max_attempts") or 3)
            queue = RedisDurableQueue(
                redis_uri,
                lease_seconds=lease,
                max_attempts=attempts,
                key_prefix=f"qpilot:swarm:{path.name}",
            )
            queue.backend = "redis"  # type: ignore[attr-defined]
            return queue
        except Exception:
            pass  # fall through to SQLite
    opened = open_durable_queue(f"sqlite:{path / 'swarm_queue.sqlite'}", **kwargs)
    if not opened.get("ready") or opened.get("queue") is None:
        raise RuntimeError(opened.get("reason") or "durable queue is not ready")
    queue = opened["queue"]
    if not getattr(queue, "backend", None):
        queue.backend = "sqlite"  # type: ignore[attr-defined]
    return queue
