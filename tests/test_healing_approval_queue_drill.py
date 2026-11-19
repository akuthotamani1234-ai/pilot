"""Healing approval queue stays incomplete for Gate E."""
from backend.healing_approval_queue_drill import run_healing_approval_queue_drill


def test_healing_approval_queue_stays_partial(tmp_path):
    evidence = run_healing_approval_queue_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["production_suite_executed"] is False
    assert evidence["ok"] is True
    assert evidence["prose_rejected"] is True
    assert evidence["assertion_rejected"] is True
    assert evidence["infrastructure_rejected"] is True
    assert evidence["first_auth_accepted"] is True
    assert evidence["second_auth_rejected"] is True
    assert (tmp_path / "healing_approval_queue_drill.json").is_file()
