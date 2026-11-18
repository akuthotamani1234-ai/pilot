"""Gate F locale portfolio drill stays incomplete and matches DemoStore expectations."""
from pathlib import Path

from backend.locale_portfolio_drill import run_locale_portfolio_drill


def test_locale_portfolio_drill_passes_demostore(tmp_path: Path):
    evidence = run_locale_portfolio_drill(ops_dir=tmp_path)
    assert evidence["gate_f_complete"] is False
    assert evidence["ok"] is True
    assert evidence["portfolio"]["verdict"] == "pass"
    assert (tmp_path / "locale_portfolio_drill.json").is_file()
