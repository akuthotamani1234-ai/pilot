"""Gate B/G Redis DurableQueue adapter (skips when Redis unavailable)."""
import shutil
import time
import uuid

import pytest

from backend.queue_backend import open_durable_queue
from backend.redis_queue import RedisDurableQueue
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


@pytest.mark.skipif(shutil.which("redis-cli") is None, reason="redis-cli missing")
def test_redis_recover_ignores_a_stale_expired_snapshot():
    prefix = f"qpilot:testrecover:{uuid.uuid4().hex}"
    queue = RedisDurableQueue(
        "redis://127.0.0.1:6379/15", lease_seconds=30, key_prefix=prefix,
    )
    original = queue._load

    def stale(task_id):
        row = original(task_id)
        if row and row.get("status") == "leased":
            row = dict(row)
            row["lease_until"] = time.time() - 30
        return row

    try:
        queue.enqueue(
            run_id="run-live", role="worker", payload={"url": "/a"},
            idempotency_key="a",
        )
        claimed = queue.claim(worker_id="w1", run_id="run-live")
        assert claimed and claimed["lease_owner"] == "w1"
        queue._load = stale
        assert queue.recover_expired() == []
        queue._load = original
        row = queue.get(claimed["task_id"])
        assert row["status"] == "leased" and row["lease_owner"] == "w1"
    finally:
        queue._load = original
        for key in queue._r.scan_iter(match=f"{prefix}:*"):
            queue._r.delete(key)
        queue.close()


def test_redis_expired_lease_cannot_complete():
    prefix = f"qpilot:testlease:{uuid.uuid4().hex}"
    queue = RedisDurableQueue(
        "redis://127.0.0.1:6379/15", lease_seconds=30, key_prefix=prefix,
    )
    try:
        queue.enqueue(
            run_id="run-lease", role="worker", payload={"url": "/a"},
            idempotency_key="a",
        )
        claimed = queue.claim(worker_id="w1", run_id="run-lease")
        assert claimed and claimed["status"] == "leased"
        queue._r.hset(
            queue._task_key(claimed["task_id"]),
            "lease_until",
            str(time.time() - 5),
        )
        ok, reason = queue.complete(claimed["task_id"], "w1", {"evidence": ["late"]})
        assert ok is False and reason == "worker does not own this lease"
        assert queue.heartbeat(claimed["task_id"], "w1") is False
        assert queue.get(claimed["task_id"])["status"] == "leased"
        assert claimed["task_id"] in queue.recover_expired()
        again = queue.claim(worker_id="w2", run_id="run-lease")
        assert again and again["lease_owner"] == "w2"
        done, _ = queue.complete(again["task_id"], "w2", {"evidence": ["ok"]})
        assert done is True
        assert queue.get(again["task_id"])["status"] == "succeeded"
    finally:
        for key in queue._r.scan_iter(match=f"{prefix}:*"):
            queue._r.delete(key)
        queue.close()
