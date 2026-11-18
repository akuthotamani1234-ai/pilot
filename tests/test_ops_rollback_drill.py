"""Gate H offline CI rollback rehearsal never marks the gate complete."""
from backend.ops_rollback_drill import run_ci_rollback_rehearsal


def test_ci_rollback_rehearsal_restores_known_good(tmp_path):
    evidence = run_ci_rollback_rehearsal(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "ci_rollback_rehearsal.json").is_file()
    assert (tmp_path / "rollback_restored" / "artifact.json").is_file()
