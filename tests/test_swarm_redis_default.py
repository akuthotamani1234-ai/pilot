"""Gate B: open_queue prefers REDIS_URL when configured."""
import os

import pytest

from backend.swarm_evidence import record_swarm
from backend.swarm_supervisor import open_queue, queue_backend_name


def test_unavailable_configured_redis_never_creates_sqlite(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setenv("REDIS_URL", "redis://localhost")
    monkeypatch.setattr("backend.redis_queue.RedisDurableQueue", unavailable)
    with pytest.raises(RuntimeError, match="Configured Redis queue is unavailable"):
        open_queue(tmp_path)
    assert not (tmp_path / "swarm_queue.sqlite").exists()


@pytest.mark.skipif(not (os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL")),
                    reason="REDIS_URL not configured")
def test_open_queue_uses_redis_when_url_set(tmp_path, monkeypatch):
    monkeypatch.setenv("REDIS_URL", os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL"))
    q = open_queue(tmp_path / "run-redis")
    try:
        assert queue_backend_name(q) == "redis"
    finally:
        q.close()
    out = record_swarm(
        tmp_path / "run-redis-ev",
        ["https://shop.example/", "https://shop.example/p/1"],
        run_id="redis-default",
    )
    assert out["backend"] == "redis"
    assert out["ran"] is True
    assert out["gate_b_complete"] is False
