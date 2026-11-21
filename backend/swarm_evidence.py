"""Gate B: run the durable supervisor over crawled URLs for lease evidence.

Also dual-writes SiteSwarm listing handoffs into the durable queue during
discovery so listing ownership is not only an in-memory protocol list.

Uses Redis when REDIS_URL is set (product default), else per-run SQLite.
gate_b_complete stays False until review.
"""
from __future__ import annotations

import json
from pathlib import Path

from .swarm import observed_page
from .swarm_supervisor import drain, enqueue_plan, open_queue, plan_run, queue_backend_name


def _url_key(value: object) -> str:
    """Keep distinct query strings, trailing slashes and client-side routes."""
    return value.strip() if isinstance(value, str) else ""


def _read_rows(path: Path, name: str) -> list[dict]:
    """Read a run-owned JSON list without following links or malformed artifacts."""
    from .finalization import folder_is_linked

    file = path / name
    if folder_is_linked(path) or file.is_symlink() or not file.is_file():
        return []
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _browser_work(path: Path) -> dict[str, dict]:
    """Index actual parallel-browser observations by their requested/final URL."""
    indexed: dict[str, dict] = {}
    for row in _read_rows(path, "swarm_work.json"):
        key = _url_key(row.get("url"))
        if not key:
            continue
        # Any HTTP response is an observation.  A 4xx/5xx is evidence of a
        # target outcome, not a reason to pretend the browser never ran.
        if not observed_page(row, key):
            continue
        indexed.setdefault(key, row)
    return indexed


def _worker_result(url: str, observations: dict[str, dict]) -> dict:
    """Return a success only when this specific worker page has browser evidence."""
    observed = observations.get(_url_key(url))
    if observed is None:
        return {
            "status": "blocked",
            "error_class": "evidence_missing",
            "detail": "no matching record exists in swarm_work.json; worker execution is not verified",
        }
    return {
        "ok": True,
        "url": url,
        "observed_status": observed["status"],
        "evidence": [{
            "kind": "browser_observation",
            "artifact": "swarm_work.json",
            "url": str(observed.get("url") or url),
            "http_status": observed["status"],
            "summary": str(observed.get("summary") or "")[:500],
        }],
    }


def approved_oracle(path: Path, url: str) -> dict | None:
    """Find a real approved assertion already generated for this run.

    The durable oracle task must not manufacture a fixture rule just to appear
    successful.  Before test design has persisted an approved assertion, the
    task remains blocked and the report says why.
    """
    from .oracle import bind_assertion

    for case in _read_rows(path, "test_cases.json"):
        source = str(case.get("expected_source") or case.get("oracle_source") or case.get("source") or "")
        if not source and case.get("generation_source") == "contract" and case.get("kind") == "contract":
            source = "contract"
        statement = case.get("expected")
        scope = case.get("url") or case.get("page_url")
        if not isinstance(statement, str) or not scope or scope != url or case.get("blocked"):
            continue
        bound = bind_assertion(
            source=source,
            statement=statement,
            scope=scope,
            requirement_id=str(case.get("requirement_id") or case.get("tc_id") or case.get("id") or ""),
            reviewed=case.get("reviewed") is True or case.get("approved") is True,
        )
        if bound.get("accepted"):
            return bound
    return None


def mirror_listing(run_dir: str | Path, listing_tasks: list[dict], *, run_id: str = "") -> dict:
    """Enqueue SiteSwarm listing handoffs into the durable queue (no drain yet)."""
    path = Path(run_dir)
    from .finalization import folder_is_linked
    if folder_is_linked(path) or (path / "swarm_queue.sqlite").is_symlink():
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
    from .finalization import folder_is_linked
    if folder_is_linked(path) or (path / "swarm_queue.sqlite").is_symlink():
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
        observations = _browser_work(path)
        from .finalization import write_text_unless_linked
        plan_artifact = {
            "run_id": rid,
            "listing_tasks": len(listing_stored),
            "planned_tasks": len(stored),
            "task_ids": [row["task_id"] for row in listing_stored + stored],
            "browser_observations": len(observations),
        }
        plan_saved = write_text_unless_linked(path, "swarm_plan.json", json.dumps(plan_artifact, indent=2))

        def work(task: dict) -> dict:
            payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
            url = payload.get("url") or task.get("url") or ""
            role = task.get("role") or payload.get("role") or ""
            if role == "leader":
                if plan_saved and task["task_id"] in plan_artifact["task_ids"]:
                    return {"ok": True, "evidence": [{"kind": "supervisor_plan", "artifact": "swarm_plan.json",
                                                       "task_id": task["task_id"]}]}
                return {"status": "blocked", "error_class": "plan_missing"}
            if role == "worker":
                return _worker_result(str(url), observations)
            if role == "coverage":
                from .coverage_verify import verify_listing
                if not observations:
                    return {
                        "status": "blocked",
                        "error_class": "evidence_missing",
                        "detail": "swarm_work.json has no browser observations; coverage is unknown",
                    }
                listed = [u for u in clean if u]
                chosen = [u for u in listed if _url_key(u) in observations]
                verdict = verify_listing(listed, chosen, [])
                return {
                    "ok": True,
                    "url": url,
                    "role": role,
                    "evidence": [{
                        "kind": "coverage_comparison",
                        "artifact": "swarm_work.json",
                        "covered": len(verdict.get("covered") or []),
                        "missed": len(verdict.get("missed") or []),
                    }],
                    "coverage": verdict,
                    "source": "observed_browser_work",
                }
            if role == "oracle":
                assertion = approved_oracle(path, str(url))
                if assertion is None:
                    return {
                        "status": "blocked",
                        "error_class": "oracle_missing",
                        "detail": "no approved assertion exists in test_cases.json",
                    }
                return {
                    "ok": True,
                    "url": url,
                    "role": role,
                    "evidence": [{
                        "kind": "approved_oracle",
                        "artifact": "test_cases.json",
                        "assertion_id": assertion.get("assertion_id"),
                        "source": assertion.get("oracle_source"),
                    }],
                    "assertion": assertion,
                    "source": "approved_test_case",
                }
            return {
                "status": "blocked",
                "error_class": "unsupported_role",
                "detail": f"no evidence handler is registered for role {role or 'unknown'}",
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
            "browser_observations": len(observations),
            "statuses": statuses,
            "tasks": [
                {
                    "task_id": t.get("task_id"),
                    "role": t.get("role"),
                    "status": t.get("status"),
                    "attempt": t.get("attempt"),
                    "url": (t.get("payload") or {}).get("url") if isinstance(t.get("payload"), dict) else "",
                    "error_class": t.get("error_class"),
                    "result": t.get("result"),
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
