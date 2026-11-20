from pathlib import Path

from backend.redis_swarm_contention_drill import run_redis_swarm_contention_drill


def test_redis_swarm_contention_reports_honestly(tmp_path: Path):
    evidence = run_redis_swarm_contention_drill(ops_dir=tmp_path)
    assert evidence["gate_b_complete"] is False
    assert (tmp_path / "redis_swarm_contention_drill.json").is_file()
    # ok requires live Redis; still always honest about gate
    assert isinstance(evidence.get("ok"), bool)
    assert evidence.get("total_claimed", 0) >= 0
