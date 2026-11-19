"""Phase 3: durable swarm queue leases, retries, checkpoints, duplicate acks."""
import time

from backend.swarm_queue import DurableQueue


def test_duplicate_enqueue_is_idempotent(tmp_path):
    q = DurableQueue(tmp_path / "swarm.db")
    first = q.enqueue(run_id="run-1", role="worker", payload={"url": "/a"}, idempotency_key="k1")
    second = q.enqueue(run_id="run-1", role="worker", payload={"url": "/a"}, idempotency_key="k1")
    assert first["task_id"] == second["task_id"]
    assert len(q.list_run("run-1")) == 1
    q.close()


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
