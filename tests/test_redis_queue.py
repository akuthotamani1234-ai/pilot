"""Gate B/G Redis DurableQueue adapter (skips when Redis unavailable)."""
import shutil

import pytest

from backend.queue_backend import open_durable_queue
from backend.swarm_supervisor import drain, enqueue_plan, plan_run


@pytest.mark.skipif(shutil.which("redis-cli") is None, reason="redis-cli missing")
def test_redis_durable_queue_plan_drain(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    opened = open_durable_queue("redis://127.0.0.1:6379/0")
    if not opened.get("ready"):
        pytest.skip(opened.get("reason") or "redis queue unavailable")
    assert opened["backend"] == "redis"
    queue = opened["queue"]
    run_id = "test-redis-queue"
    try:
        planned = plan_run(run_id, ["https://shop.example/", "https://shop.example/p/1"], worker_count=1)
        enqueue_plan(queue, run_id, planned)

        def work(task):
            return {"ok": True, "role": task.get("role")}

        summary = drain(queue, run_id=run_id, worker_id="t1", work=work)
        drain(queue, run_id=run_id, worker_id="t1", work=work)
        assert summary["processed"] >= 1
        roles = {t["role"] for t in queue.list_run(run_id)}
        assert "coverage" in roles and "oracle" in roles
    finally:
        queue.close()
