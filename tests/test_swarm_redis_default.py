"""Gate B: open_queue prefers REDIS_URL when configured."""
import os

import pytest

from backend.swarm_evidence import record_swarm
from backend.swarm_supervisor import open_queue, queue_backend_name


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
