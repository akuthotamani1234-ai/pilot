"""Gate B swarm retry drill stays incomplete and recovers expired leases."""
from pathlib import Path

from backend.swarm_retry_drill import run_swarm_retry_drill


def test_swarm_retry_drill_recovers_expired_lease(tmp_path: Path, monkeypatch):
    # Keep the drill offline/deterministic on SQLite for CI.
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("QPILOT_REDIS_URL", raising=False)
    evidence = run_swarm_retry_drill(ops_dir=tmp_path)
    assert evidence["gate_b_complete"] is False
    assert evidence["ok"] is True
    assert evidence["status_after_recover"] == "retry_wait"
    assert evidence["error_class"] == "lease_expired"
    assert evidence["reclaimed"] is True
    assert int(evidence["reclaim_attempt"] or 0) >= 2
    assert (tmp_path / "swarm_retry_drill.json").is_file()
