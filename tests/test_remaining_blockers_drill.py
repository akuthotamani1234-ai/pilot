from pathlib import Path

from backend.blueprint_progress import progress
from backend.remaining_blockers_drill import run_remaining_blockers_drill


def test_remaining_blockers_inventory_stays_open(tmp_path: Path):
    evidence = run_remaining_blockers_drill(ops_dir=tmp_path)
    assert evidence.get("complete") is False
    assert evidence.get("ok") is True
    assert evidence.get("open_count") == 6
    assert (tmp_path / "remaining_blockers.json").is_file()


def test_blueprint_progress_exposes_blockers():
    snap = progress()
    assert snap["complete"] is False
    assert "blockers" in snap
    assert snap["counts"]["blockers_open"] == len(snap["blockers"])
    assert snap["counts"]["blockers_open"] >= 5
