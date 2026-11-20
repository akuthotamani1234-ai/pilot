"""Gate B/G: exercise RedisDurableQueue plan/drain end-to-end."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "redis_durable_queue_drill.json"


def _linked_queue() -> dict:
    return {
        "gate_b_complete": False,
        "gate_g_complete": False,
        "ok": False,
        "drill": "redis_durable_queue_plan_drain",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def durable_queue_drill(*, url: str | None = None, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "redis_durable_queue_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_queue()

    from .queue_backend import open_durable_queue
    from .swarm_supervisor import drain, enqueue_plan, plan_run

    target = (url or os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL")
              or "redis://127.0.0.1:6379/0").strip()
    evidence = {
        "gate_b_complete": False,
        "gate_g_complete": False,
        "drill": "redis_durable_queue_plan_drain",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ok": False,
        "reason": "",
    }
    opened = open_durable_queue(target)
    evidence["open"] = {"ready": opened.get("ready"), "backend": opened.get("backend"),
                        "reason": opened.get("reason")}
    if not opened.get("ready") or opened.get("backend") != "redis":
        evidence["reason"] = opened.get("reason") or "redis queue not ready"
        return evidence
    queue = opened["queue"]
    run_id = f"redis-drill-{int(time.time())}"
    try:
        planned = plan_run(run_id, ["https://shop.example/", "https://shop.example/p/1"], worker_count=2)
        enqueue_plan(queue, run_id, planned)

        def work(task):
            return {"ok": True, "role": task.get("role"), "url": (task.get("payload") or {}).get("url")}

        summary = drain(queue, run_id=run_id, worker_id="redis-drill", work=work)
        again = drain(queue, run_id=run_id, worker_id="redis-drill", work=work)
        tasks = again.get("tasks") or summary.get("tasks") or []
        statuses = sorted({t.get("status") for t in tasks})
        roles = sorted({t.get("role") for t in tasks})
        ok = (
            int(summary.get("processed") or 0) + int(again.get("processed") or 0) >= 1
            and "failed" not in statuses
            and "coverage" in roles
            and "oracle" in roles
        )
        evidence.update({
            "ok": ok,
            "processed": int(summary.get("processed") or 0) + int(again.get("processed") or 0),
            "statuses": statuses,
            "roles": roles,
            "reason": (
                "Redis DurableQueue plan/drain with specialist roles verified; "
                "product-wide Redis default + review still open"
                if ok else "Redis DurableQueue drain assertions failed"
            ),
        })
    finally:
        try:
            queue.close()
        except Exception:
            pass
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_queue()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_queue()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
