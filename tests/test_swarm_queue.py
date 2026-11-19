"""Phase 3: durable swarm queue leases, retries, checkpoints, duplicate acks."""
import threading
import time

import pytest

from backend.swarm_queue import DurableQueue


def test_duplicate_enqueue_is_idempotent(tmp_path):
    q = DurableQueue(tmp_path / "swarm.db")
    first = q.enqueue(run_id="run-1", role="worker", payload={"url": "/a"}, idempotency_key="k1")
    second = q.enqueue(run_id="run-1", role="worker", payload={"url": "/a"}, idempotency_key="k1")
    assert first["task_id"] == second["task_id"]
    assert len(q.list_run("run-1")) == 1
    q.close()


def test_concurrent_enqueue_returns_one_task(tmp_path):
    path = tmp_path / "swarm.db"
    queues = [DurableQueue(path) for _ in range(8)]
    barrier = threading.Barrier(8)
    found: list[str] = []

    def go(queue):
        barrier.wait()
        row = queue.enqueue(
            run_id="run-1", role="worker", payload={"url": "/a"}, idempotency_key="k1",
        )
        found.append(row["task_id"])

    threads = [threading.Thread(target=go, args=(queue,)) for queue in queues]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(found)) == 1
    assert len(queues[0].list_run("run-1")) == 1
    for queue in queues:
        queue.close()


def test_lease_heartbeat_and_exclusive_claim(tmp_path):
    q = DurableQueue(tmp_path / "swarm.db", lease_seconds=30)
    q.enqueue(run_id="run-1", role="worker", payload={"url": "/a"}, idempotency_key="a")
    claimed = q.claim(worker_id="w1")
    assert claimed and claimed["status"] == "leased" and claimed["attempt"] == 1
    assert q.claim(worker_id="w2") is None  # only one pending task, already leased
    assert q.heartbeat(claimed["task_id"], "w1") is True
    assert q.heartbeat(claimed["task_id"], "w2") is False
    ok, _ = q.complete(claimed["task_id"], "w1", {"evidence": ["ok"]})
    assert ok
    again, reason = q.complete(claimed["task_id"], "w1", {"evidence": ["ok"]})
    assert again and reason == "already succeeded"
    q.close()


def test_recover_leaves_a_live_lease(tmp_path):
    q = DurableQueue(tmp_path / "swarm.db", lease_seconds=30)
    q.enqueue(run_id="run-1", role="worker", payload={"url": "/a"}, idempotency_key="a")
    claimed = q.claim(worker_id="w1")
    assert q.recover_expired() == []
    row = q.get(claimed["task_id"])
    assert row["status"] == "leased" and row["lease_owner"] == "w1"
    q.close()


def test_expired_lease_is_requeued_then_retryable(tmp_path):
    q = DurableQueue(tmp_path / "swarm.db", lease_seconds=1, max_attempts=3)
    task = q.enqueue(run_id="run-1", role="worker", payload={"url": "/a"}, idempotency_key="a")
    claimed = q.claim(worker_id="w1")
    assert claimed["task_id"] == task["task_id"]
    # Force expiry without waiting on flaky sleep boundaries.
    q._db.execute("UPDATE tasks SET lease_until=? WHERE task_id=?", (time.time() - 1, claimed["task_id"]))
    q._db.commit()
    recovered = q.recover_expired()
    assert claimed["task_id"] in recovered
    row = q.get(claimed["task_id"])
    assert row["status"] == "retry_wait"
    assert row["lease_owner"] is None
    again = q.claim(worker_id="w2")
    assert again and again["attempt"] == 2 and again["lease_owner"] == "w2"
    q.close()


def test_expired_lease_cannot_ack(tmp_path):
    q = DurableQueue(tmp_path / "swarm.db", lease_seconds=30, max_attempts=3)
    q.enqueue(run_id="run-1", role="worker", payload={"url": "/a"}, idempotency_key="a")
    claimed = q.claim(worker_id="w1")
    q._db.execute(
        "UPDATE tasks SET lease_until=? WHERE task_id=?",
        (time.time() - 1, claimed["task_id"]),
    )
    q._db.commit()
    ok, reason = q.complete(claimed["task_id"], "w1", {"evidence": ["late"]})
    assert ok is False and reason == "worker does not own this lease"
    assert q.heartbeat(claimed["task_id"], "w1") is False
    assert q.checkpoint(claimed["task_id"], "w1", {"step": 1}) is False
    failed, fail_reason = q.fail(
        claimed["task_id"], "w1", error_class="network", detail="late",
    )
    assert failed is False and fail_reason == "worker does not own this lease"
    assert q.get(claimed["task_id"])["status"] == "leased"
    assert claimed["task_id"] in q.recover_expired()
    assert q.get(claimed["task_id"])["status"] == "retry_wait"
    q.close()


def test_transient_failure_retries_until_budget(tmp_path):
    q = DurableQueue(tmp_path / "swarm.db", lease_seconds=30, max_attempts=2)
    q.enqueue(run_id="run-1", role="crawler", payload={"url": "/x"}, idempotency_key="x")
    first = q.claim(worker_id="w1")
    ok, msg = q.fail(first["task_id"], "w1", error_class="network", detail="timeout")
    assert ok and msg == "scheduled retry"
    assert q.get(first["task_id"])["status"] == "retry_wait"
    second = q.claim(worker_id="w1")
    assert second["attempt"] == 2
    ok, msg = q.fail(second["task_id"], "w1", error_class="network", detail="timeout again")
    assert ok and msg == "attempts exhausted"
    assert q.get(second["task_id"])["status"] == "failed"
    q.close()


def test_checkpoint_survives_for_resume(tmp_path):
    q = DurableQueue(tmp_path / "swarm.db")
    q.enqueue(run_id="run-1", role="worker", payload={"url": "/p"}, idempotency_key="p")
    claimed = q.claim(worker_id="w1")
    assert q.checkpoint(claimed["task_id"], "w1", {"page": "/p", "step": 2})
    row = q.get(claimed["task_id"])
    assert row["checkpoint"] == {"page": "/p", "step": 2}
    q.close()


def test_cancel_blocks_further_claims(tmp_path):
    q = DurableQueue(tmp_path / "swarm.db")
    task = q.enqueue(run_id="run-1", role="worker", payload={"url": "/z"}, idempotency_key="z")
    assert q.cancel(task["task_id"])
    assert q.claim(worker_id="w1") is None
    assert q.get(task["task_id"])["status"] == "cancelled"
    q.close()


def test_a_swarm_queue_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    from backend.swarm_evidence import record_swarm
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("QPILOT_REDIS_URL", raising=False)
    secret = b"tenant-b-only-queue"
    other = tmp_path / "other"
    other.mkdir()
    victim = other / "swarm_queue.sqlite"
    victim.write_bytes(secret)
    (other / "note.txt").write_text("tenant-b-only-queue", encoding="utf-8")

    linked_dir = tmp_path / "linked-dir"
    linked_dir.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError):
        DurableQueue(linked_dir / "swarm_queue.sqlite")
    assert victim.read_bytes() == secret
    assert not (other / "swarm_queue.sqlite-wal").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "swarm_queue.sqlite").symlink_to(victim)
    with pytest.raises(ValueError):
        DurableQueue(real / "swarm_queue.sqlite")
    evidence = record_swarm(real, ["https://shop.example/saree"], run_id="real")
    assert evidence["ran"] is False
    assert victim.read_bytes() == secret
    assert (other / "note.txt").read_text(encoding="utf-8") == "tenant-b-only-queue"

    fresh = tmp_path / "fresh"
    saved = record_swarm(fresh, ["https://shop.example/saree"], run_id="fresh")
    assert saved["ran"] is True
    queue = fresh / "swarm_queue.sqlite"
    assert queue.is_file() and not queue.is_symlink()
    assert secret not in queue.read_bytes()
