"""Gate C offline lifecycle cleanup drill stays incomplete and confirms deletes."""
from pathlib import Path

from backend.lifecycle_cleanup_drill import run_lifecycle_cleanup_drill


def test_lifecycle_cleanup_drill_confirms_without_claiming_complete(tmp_path: Path):
    evidence = run_lifecycle_cleanup_drill(ops_dir=tmp_path, work_dir=tmp_path / "work")
    assert evidence["gate_c_complete"] is False
    assert evidence["ok"] is True
    assert evidence["confirmed"] >= 4  # 3 synthetic + 1 created.jsonl
    assert evidence["failed"] == 0
    assert evidence["local_only"] is False
    assert (tmp_path / "lifecycle_cleanup_drill.json").is_file()
