"""Gate B swarm control drill stays incomplete and cancels after checkpoint."""
from pathlib import Path

from backend.swarm_control_drill import run_swarm_control_drill


def test_swarm_control_drill_cancels_after_checkpoint(tmp_path: Path):
    evidence = run_swarm_control_drill(ops_dir=tmp_path, run_id="test-swarm-control")
    assert evidence["gate_b_complete"] is False
    assert evidence["claimed"] is True
    assert evidence["checkpointed"] is True
    assert evidence["cancelled"] is True
    assert evidence["final_status"] == "cancelled"
    assert evidence["ok"] is True
    assert (tmp_path / "swarm_control_drill.json").is_file()
