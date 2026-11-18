"""Gate H: ops readiness never claims complete from docs alone."""
from backend.ops_readiness import readiness


def test_ops_readiness_lists_gaps_and_stays_incomplete():
    snap = readiness()
    assert snap["gate_h_complete"] is False
    # Local drill evidence under artifacts/ops may be present after a drill POST;
    # load/incident remain open either way.
    assert "ci_workflow" in snap["checks"]
    assert snap["checks"]["ops_drill_checklist"]["ready"] is True
    assert "ops_drill_checklist" in snap["ready"]
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]

    def has(name: str) -> bool:
        return (
            (root / "artifacts" / "ops" / name).is_file()
            or (root / "docs" / "ops-evidence" / name).is_file()
        )

    assert snap["checks"]["backup_restore_drill"]["ready"] is has("backup_restore_drill.json")
    assert snap["checks"]["load_test"]["ready"] is has("local_load_probe.json")
    assert snap["checks"]["controlled_soak"]["ready"] is has("controlled_soak_drill.json")
    if has("local_load_probe.json"):
        assert "load_test" in snap["ready"]
    else:
        assert "load_test" in snap["missing"]
    if has("controlled_soak_drill.json"):
        assert "controlled_soak" in snap["ready"]
    else:
        assert "controlled_soak" in snap["missing"]
