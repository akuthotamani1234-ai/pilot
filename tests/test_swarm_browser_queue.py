"""Milestone 2 proves the real browser adapter claims before opening a page."""

import shutil
from pathlib import Path
from uuid import uuid4

from backend.swarm import SiteSwarm
from backend.swarm_queue import DurableQueue


def test_browser_worker_claims_durable_task_before_session_starts():
    run_dir = Path.cwd() / f".m2-browser-queue-{uuid4().hex}"
    run_dir.mkdir()
    queue = DurableQueue(run_dir / "queue.sqlite")
    observed = []

    def session():
        task_id = next(iter(queue.list_run("browser-run")))["task_id"]
        task = queue.get(task_id)
        observed.append((task_id, task["status"], task["lease_owner"]))

        def open_page(url):
            return {"url": url, "status": 200, "final_url": url, "summary": "fixture"}

        return open_page, lambda: None

    swarm = SiteSwarm(
        1,
        1,
        session,
        durable_queue=queue,
        run_id="browser-run",
        evidence_dir=run_dir,
    )
    assigned = swarm.submit(["https://shop.example/item"])
    rows = swarm.finish()
    task = queue.get(assigned[0]["task_id"])
    queue.close()
    shutil.rmtree(run_dir)

    assert observed == [(assigned[0]["task_id"], "leased", "browser-browser-run-1")]
    assert rows[0]["durable_status"] == "succeeded"
    assert task["status"] == "succeeded"
    assert task["result"]["evidence"][0]["task_id"] == assigned[0]["task_id"]

