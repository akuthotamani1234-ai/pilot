"""Gate B/G: queue backend selector opens SQLite by default; Redis when adapter ready."""
from backend.queue_backend import open_durable_queue


def test_default_opens_sqlite_durable_queue(tmp_path):
    opened = open_durable_queue(f"sqlite:{tmp_path / 'q.sqlite'}")
    assert opened["ready"] is True
    assert opened["backend"] == "sqlite"
    q = opened["queue"]
    task = q.enqueue(run_id="run-1", role="oracle", payload={"x": 1}, idempotency_key="k1")
    assert task["task_id"]
    leased = q.claim(worker_id="worker-a")
    assert leased["task_id"] == task["task_id"]


def test_redis_uri_opens_adapter_or_reports_unready():
    opened = open_durable_queue("redis://127.0.0.1:6379/0")
    if opened["ready"]:
        assert opened["backend"] == "redis"
        assert opened["queue"] is not None
        opened["queue"].close()
    else:
        assert opened["queue"] is None
        assert "unavailable" in opened["reason"] or "not" in opened["reason"]
