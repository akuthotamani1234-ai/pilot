"""Gate H: ops readiness never claims complete from docs alone."""
from backend.ops_readiness import readiness


def test_ops_readiness_lists_gaps_and_stays_incomplete():
    snap = readiness()
    assert snap["gate_h_complete"] is False
    # Local drill evidence under artifacts/ops may be present after a drill POST;
    # load/incident remain open either way.
    assert "load_test" in snap["missing"]
    assert "ci_workflow" in snap["checks"]
    assert snap["checks"]["ops_drill_checklist"]["ready"] is True
    assert "ops_drill_checklist" in snap["ready"]
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    has_backup = (
        (root / "artifacts" / "ops" / "backup_restore_drill.json").is_file()
        or (root / "docs" / "ops-evidence" / "backup_restore_drill.json").is_file()
    )
    assert snap["checks"]["backup_restore_drill"]["ready"] is has_backup
