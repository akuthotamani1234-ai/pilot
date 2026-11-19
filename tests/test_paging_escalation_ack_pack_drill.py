"""Paging escalation+ack pack stays incomplete for Gate H."""
from backend.paging_escalation_ack_pack_drill import (
    run_paging_escalation_ack_pack_drill,
)


def test_paging_escalation_ack_pack_stays_partial(tmp_path):
    evidence = run_paging_escalation_ack_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["ok"] is True
    assert evidence["escalation_ok"] is True
    assert evidence["ack_ok"] is True
    assert (tmp_path / "paging_escalation_ack_pack_drill.json").is_file()
