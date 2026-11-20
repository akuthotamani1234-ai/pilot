"""Gate H controlled AdminPortal soak stays incomplete and writes evidence."""
from pathlib import Path

from backend.ops_soak_drill import run_controlled_soak


def test_controlled_soak_writes_evidence(tmp_path: Path):
    evidence = run_controlled_soak(duration_s=6.0, ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["drill"] == "controlled_fixture_soak"
    assert evidence["ok"] >= 6
    assert evidence["fail"] == 0
    assert (tmp_path / "controlled_soak_drill.json").is_file()
