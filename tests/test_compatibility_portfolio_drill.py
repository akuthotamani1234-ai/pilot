"""Gate F compatibility portfolio drill stays incomplete and records viewports."""
from pathlib import Path

from backend.compatibility_portfolio_drill import run_compatibility_portfolio_drill


def test_compatibility_portfolio_drill_records_viewports(tmp_path: Path):
    evidence = run_compatibility_portfolio_drill(ops_dir=tmp_path)
    assert evidence["gate_f_complete"] is False
    assert evidence["ok"] is True
    assert evidence["matrix"]["desktop"] >= 1
    assert evidence["matrix"]["mobile"] >= 1
    assert "chromium" in evidence["matrix"]["browsers"]
    assert evidence["portfolio"]["verdict"] == "pass"
    assert (tmp_path / "compatibility_portfolio_drill.json").is_file()
