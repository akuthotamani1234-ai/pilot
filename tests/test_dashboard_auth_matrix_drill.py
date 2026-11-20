"""Gate I dashboard auth matrix drill stays incomplete and covers all modes."""
from pathlib import Path

from backend.dashboard_auth_matrix_drill import run_dashboard_auth_matrix_drill


def test_dashboard_auth_matrix_covers_all_modes(tmp_path: Path):
    evidence = run_dashboard_auth_matrix_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["ok"] is True
    assert evidence["failed"] == 0
    assert set(evidence["modes_covered"]) == {"none", "bearer", "webhook", "principal", "oidc"}
    assert (tmp_path / "dashboard_auth_matrix_drill.json").is_file()
