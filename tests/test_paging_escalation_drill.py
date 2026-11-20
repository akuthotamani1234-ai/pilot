from pathlib import Path

from backend.paging_escalation_drill import run_paging_escalation_drill


def test_paging_escalation_hits_secondary(tmp_path: Path):
    evidence = run_paging_escalation_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence.get("ok") is True
    assert evidence.get("escalated") is True
    assert (tmp_path / "paging_escalation_drill.json").is_file()
