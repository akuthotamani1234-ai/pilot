"""Gate B: run the durable supervisor over crawled URLs for lease evidence.

This does not re-crawl pages. It plans, enqueues, and drains durable queue tasks
for the URLs already visited so apply_run/report have real lease/complete rows.
Redis enterprise queue remains open — this is local SQLite wiring only.
"""
from __future__ import annotations

import json
from pathlib import Path

from .swarm_supervisor import drain, enqueue_plan, open_queue, plan_run


def record_swarm(run_dir: str | Path, urls: list[str], *, run_id: str = "",
                 worker_count: int = 2, limit: int = 40) -> dict:
    """Plan + drain durable tasks for safe URLs. Writes swarm_evidence.json."""
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    rid = (run_id or path.name or "run").strip()
    clean = [u for u in urls if isinstance(u, str) and u.strip()][: max(1, int(limit))]
    if not clean:
        evidence = {
            "gate_b_complete": False,
            "ran": False,
            "reason": "no crawled URLs to schedule",
            "backend": "sqlite",
            "processed": 0,
            "tasks": [],
        }
        (path / "swarm_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        return evidence
    queue = open_queue(path)
    try:
        planned = plan_run(rid, clean, worker_count=max(1, int(worker_count)), limit=limit)
        stored = enqueue_plan(queue, rid, planned)

        def work(task: dict) -> dict:
            payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
            url = payload.get("url") or ""
            return {
                "ok": True,
                "url": url,
                "evidence": [f"durable-ack:{url}" if url else "durable-ack:leader"],
                "role": task.get("role") or payload.get("role") or "",
            }

        summary = drain(queue, run_id=rid, worker_id="discovery-supervisor", work=work)
        # Recover one retry_wait pass if a transient fail left work pending.
        again = drain(queue, run_id=rid, worker_id="discovery-supervisor", work=work)
        tasks = again.get("tasks") or summary.get("tasks") or []
        statuses = sorted({str(t.get("status") or "") for t in tasks})
        evidence = {
            "gate_b_complete": False,
            "ran": True,
            "reason": "local SQLite durable plan/drain; Redis/Postgres enterprise queue still open",
            "backend": "sqlite",
            "run_id": rid,
            "urls_planned": len(clean),
            "tasks_enqueued": len(stored),
            "processed": int(summary.get("processed") or 0) + int(again.get("processed") or 0),
            "statuses": statuses,
            "tasks": [
                {
                    "task_id": t.get("task_id"),
                    "role": t.get("role"),
                    "status": t.get("status"),
                    "attempt": t.get("attempt"),
                    "url": (t.get("payload") or {}).get("url") if isinstance(t.get("payload"), dict) else "",
                }
                for t in tasks[:80]
            ],
        }
    finally:
        try:
            queue.close()
        except Exception:
            pass
    (path / "swarm_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
