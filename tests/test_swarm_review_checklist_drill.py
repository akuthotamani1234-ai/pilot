from pathlib import Path

from backend.swarm_review_checklist_drill import run_swarm_review_checklist_drill


def test_swarm_review_checklist_stays_unsigned(tmp_path: Path):
    evidence = run_swarm_review_checklist_drill(ops_dir=tmp_path)
    assert evidence["gate_b_complete"] is False
    assert evidence.get("signed_off") is False
    assert evidence.get("ok") is True
    assert (tmp_path / "swarm_review_checklist.json").is_file()
