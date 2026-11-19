"""Paging ack→resolve lifecycle stays incomplete for Gate H."""
from backend.paging_ack_drill import run_paging_ack_drill


def test_paging_ack_lifecycle_stays_partial(tmp_path):
    evidence = run_paging_ack_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["ok"] is True
    assert evidence["lifecycle"] == ["page", "ack", "resolve"]
    assert (tmp_path / "paging_ack_drill.json").is_file()
