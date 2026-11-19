"""Gate B: run the durable supervisor over crawled URLs for lease evidence.

Also dual-writes SiteSwarm listing handoffs into the durable queue during
discovery so listing ownership is not only an in-memory protocol list.

Uses Redis when REDIS_URL is set (product default), else per-run SQLite.
gate_b_complete stays False until review.
"""
from __future__ import annotations

import json
from pathlib import Path

from .swarm_supervisor import drain, enqueue_plan, open_queue, plan_run, queue_backend_name


def mirror_listing(run_dir: str | Path, listing_tasks: list[dict], *, run_id: str = "") -> dict:
    """Enqueue SiteSwarm listing handoffs into the durable queue (no drain yet)."""
    path = Path(run_dir)
    if path.is_symlink() or (path / "swarm_queue.sqlite").is_symlink():
        return {"mirrored": 0, "run_id": run_id or path.name or "run", "backend": "none"}
    path.mkdir(parents=True, exist_ok=True)
    rid = (run_id or path.name or "run").strip()
    tasks = [t for t in (listing_tasks or []) if isinstance(t, dict)]
    if not tasks:
        return {"mirrored": 0, "run_id": rid, "backend": "none"}
    queue = open_queue(path)
    backend = queue_backend_name(queue)
    try:
        stored = enqueue_plan(queue, rid, tasks)
        note = {
            "mirrored": len(stored),
            "run_id": rid,
            "backend": backend,
            "at": "listing",
            "gate_b_complete": False,
            "reason": (
                f"SiteSwarm listing dual-written to durable {backend}; Gate B review still open"
            ),
        }
        from .finalization import write_text_unless_linked
        write_text_unless_linked(path, "swarm_listing_mirror.json", json.dumps(note, indent=2))
        return note
    finally:
        try:
            queue.close()
        except Exception:
            pass


def record_swarm(run_dir: str | Path, urls: list[str], *, run_id: str = "",
                 worker_count: int = 2, limit: int = 40,
                 listing_tasks: list[dict] | None = None) -> dict:
    """Plan + drain durable tasks for safe URLs. Optionally enqueue listing tasks first."""
    path = Path(run_dir)
    if path.is_symlink() or (path / "swarm_queue.sqlite").is_symlink():
        return {"gate_b_complete": False, "ran": False, "reason": "The swarm queue is a link.",
                "backend": "none", "processed": 0, "tasks": [], "listing_mirrored": 0}
    path.mkdir(parents=True, exist_ok=True)
    rid = (run_id or path.name or "run").strip()
    clean = [u for u in urls if isinstance(u, str) and u.strip()][: max(1, int(limit))]
    listing = [t for t in (listing_tasks or []) if isinstance(t, dict)]
    if not clean and not listing:
        evidence = {
            "gate_b_complete": False,
            "ran": False,
            "reason": "no crawled URLs to schedule",
            "backend": "none",
            "processed": 0,
            "tasks": [],
            "listing_mirrored": 0,
        }
        from .finalization import write_text_unless_linked
        write_text_unless_linked(path, "swarm_evidence.json", json.dumps(evidence, indent=2))
        return evidence
    queue = open_queue(path)
    backend = queue_backend_name(queue)
    try:
        listing_stored = enqueue_plan(queue, rid, listing) if listing else []
        planned = plan_run(rid, clean, worker_count=max(1, int(worker_count)), limit=limit) if clean else []
        stored = enqueue_plan(queue, rid, planned) if planned else []

        def work(task: dict) -> dict:
            payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
            url = payload.get("url") or task.get("url") or ""
            role = task.get("role") or payload.get("role") or ""
            if role == "coverage":
                from .coverage_verify import verify_listing
                listed = [u for u in clean if u]
                chosen = listed[: max(1, min(3, len(listed)))]
                skipped = [(u, "sampled_out") for u in listed[len(chosen):]]
                verdict = verify_listing(listed, chosen, skipped)
                return {
                    "ok": bool(verdict.get("complete") or not verdict.get("missed")),
                    "url": url,
                    "role": role,
                    "evidence": [f"coverage:covered={len(verdict.get('covered') or [])}",
                                 f"coverage:missed={len(verdict.get('missed') or [])}"],
                    "coverage": verdict,
                    "source": "specialist",
                }
            if role == "oracle":
                from .oracle import bind_assertion
                assertion = bind_assertion(
                    source="fixture",
                    statement="durable swarm oracle task binds an approved fixture assertion",
                    scope=url or "site",
                    requirement_id="gate-b-oracle",
                )
                return {
                    "ok": bool(assertion.get("accepted")),
                    "url": url,
                    "role": role,
                    "evidence": [f"oracle:{assertion.get('status')}:{assertion.get('assertion_id')}"],
                    "assertion": assertion,
                    "source": "specialist",
                }
            return {
                "ok": True,
                "url": url,
                "evidence": [f"durable-ack:{url}" if url else "durable-ack:leader"],
                "role": role,
                "source": "listing" if payload.get("scope") == "listing" else "url_plan",
            }

        summary = drain(queue, run_id=rid, worker_id="discovery-supervisor", work=work)
        again = drain(queue, run_id=rid, worker_id="discovery-supervisor", work=work)
        tasks = again.get("tasks") or summary.get("tasks") or []
        statuses = sorted({str(t.get("status") or "") for t in tasks})
        evidence = {
            "gate_b_complete": False,
            "ran": True,
            "reason": (
                f"durable {backend} plan/drain (+ listing dual-write); "
                "Gate B product-wide review still open"
            ),
            "backend": backend,
            "run_id": rid,
            "urls_planned": len(clean),
            "listing_mirrored": len(listing_stored),
            "tasks_enqueued": len(stored) + len(listing_stored),
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
    from .finalization import write_text_unless_linked
    write_text_unless_linked(path, "swarm_evidence.json", json.dumps(evidence, indent=2))
    return evidence
