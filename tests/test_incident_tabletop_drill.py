"""Gate H incident tabletop drill stays incomplete and cross-checks local evidence."""
from pathlib import Path

from backend.incident_tabletop_drill import run_incident_tabletop_drill


def test_incident_tabletop_drill_stays_incomplete(tmp_path: Path):
    # Seed local evidence files the drill looks for under ops_dir-equivalent paths via docs/.
    # Drill checks repo docs/ops-evidence + artifacts/ops; those already exist in this repo.
    evidence = run_incident_tabletop_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["ok"] is True
    assert evidence["runbook_present"] is True
    assert "local_operator" in evidence["roles_exercised"]
    assert "on_call" not in evidence["roles_exercised"]
    assert (tmp_path / "incident_tabletop_drill.json").is_file()
