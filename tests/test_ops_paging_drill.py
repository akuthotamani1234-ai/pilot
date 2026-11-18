"""Gate H local paging rehearsal never completes the gate."""
from backend.ops_paging_drill import run_paging_rehearsal


def test_paging_rehearsal_hits_loopback_sink(tmp_path):
    evidence = run_paging_rehearsal(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["ok"] is True
    assert evidence["received_count"] >= 1
    assert (tmp_path / "paging_rehearsal.json").is_file()
