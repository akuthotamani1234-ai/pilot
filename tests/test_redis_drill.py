"""Gate G/B Redis lease drill (skips when redis-cli cannot reach Redis)."""
import shutil

import pytest

from backend.redis_drill import lease_drill


@pytest.mark.skipif(shutil.which("redis-cli") is None, reason="redis-cli missing")
def test_redis_lease_drill_against_local(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    evidence = lease_drill()
    if not evidence.get("ok"):
        pytest.skip(evidence.get("reason") or "redis unavailable")
    assert evidence["gate_g_complete"] is False
    assert evidence["gate_b_complete"] is False
    assert evidence["first_claim"] == "OK"
