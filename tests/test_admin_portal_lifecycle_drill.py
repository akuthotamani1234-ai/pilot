"""Gate C AdminPortal lifecycle drill stays incomplete and confirms delete."""
from pathlib import Path

from backend.admin_portal_lifecycle_drill import run_admin_portal_lifecycle_drill


def test_admin_portal_lifecycle_drill_confirms_delete(tmp_path: Path):
    evidence = run_admin_portal_lifecycle_drill(ops_dir=tmp_path)
    assert evidence["gate_c_complete"] is False
    assert evidence["ok"] is True
    assert evidence["confirmed"] >= 1
    assert evidence["failed"] == 0
    assert evidence["user_removed"] is True
    assert (tmp_path / "admin_portal_lifecycle_drill.json").is_file()
