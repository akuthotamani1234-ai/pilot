"""Gate I approvals drill stays incomplete and decides pending items."""
from pathlib import Path

from backend.approvals_drill import run_approvals_drill


def test_approvals_drill_accepts_and_rejects(tmp_path: Path):
    evidence = run_approvals_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["ok"] is True
    assert evidence["accepted_status"] == "accepted"
    assert evidence["rejected_status"] == "rejected"
    assert evidence["pending_after"] == 0
    assert (tmp_path / "approvals_drill.json").is_file()
