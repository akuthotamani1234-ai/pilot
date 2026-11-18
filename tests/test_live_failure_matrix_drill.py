"""Gate E live failure matrix stays incomplete."""
from pathlib import Path

from backend.live_failure_matrix_drill import run_live_failure_matrix_drill


def test_live_failure_matrix_drill_reports_honestly(tmp_path: Path):
    evidence = run_live_failure_matrix_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert (tmp_path / "live_failure_matrix_drill.json").is_file()
    assert evidence.get("ok") is True
    assert int(evidence.get("failed") or 0) >= 2
    assert evidence["healing"]["locator_repair_allowed"] is True
    assert evidence["healing"]["weaken_denied"] is True
