"""Gate F visual portfolio drill stays incomplete and records first-run pages."""
from pathlib import Path

from backend.visual_portfolio_drill import run_visual_portfolio_drill


def test_visual_portfolio_drill_records_first_run_pages(tmp_path: Path):
    evidence = run_visual_portfolio_drill(ops_dir=tmp_path)
    assert evidence["gate_f_complete"] is False
    assert evidence["ok"] is True
    assert evidence["pages_recorded"] >= 1
    assert evidence["portfolio"]["verdict"] == "pass"  # first-run: no changes
    assert (tmp_path / "visual_portfolio_drill.json").is_file()
