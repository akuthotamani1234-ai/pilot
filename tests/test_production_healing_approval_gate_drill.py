"""Healing approval gate stays incomplete for Gate E."""
from backend.production_healing_approval_gate_drill import (
    run_production_healing_approval_gate_drill,
)


def test_production_healing_approval_gate_stays_partial(tmp_path):
    evidence = run_production_healing_approval_gate_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["production_suite_executed"] is False
    assert evidence["ok"] is True
    assert evidence["auth_without_token_blocked"] is True
    assert evidence["auth_with_token_allowed"] is True
    assert evidence["token_reuse_blocked"] is True
    assert evidence["assertion_change_blocked"] is True
    assert evidence["infrastructure_not_approvable"] is True
    assert (tmp_path / "production_healing_approval_gate_drill.json").is_file()
