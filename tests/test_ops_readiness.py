"""Gate H: ops readiness never claims complete from docs alone."""
from backend.ops_readiness import readiness


def test_ops_readiness_lists_gaps_and_stays_incomplete():
    snap = readiness()
    assert snap["gate_h_complete"] is False
    assert "observability" in snap["missing"]
    assert "backup_restore_drill" in snap["missing"]
    assert "load_test" in snap["missing"]
    assert "ci_workflow" in snap["checks"]
