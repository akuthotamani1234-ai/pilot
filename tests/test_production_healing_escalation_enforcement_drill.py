"""Healing escalation enforcement stays incomplete for Gate E."""
from backend.production_healing_escalation_enforcement_drill import (
    run_production_healing_escalation_enforcement_drill,
)


def test_production_healing_escalation_enforcement_stays_partial(tmp_path):
    evidence = run_production_healing_escalation_enforcement_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["production_suite_executed"] is False
    assert evidence["ok"] is True
    assert evidence["auth_blocked"] is True
    assert evidence["infrastructure_blocked"] is True
    assert evidence["timeout_allowed"] is True
    assert (
        tmp_path / "production_healing_escalation_enforcement_drill.json"
    ).is_file()
