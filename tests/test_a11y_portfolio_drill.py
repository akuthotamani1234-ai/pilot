"""Gate F a11y portfolio drill stays incomplete."""
from pathlib import Path

from backend.a11y_portfolio_drill import run_a11y_portfolio_drill


def test_a11y_portfolio_drill_evaluates_demostore(tmp_path: Path):
    evidence = run_a11y_portfolio_drill(ops_dir=tmp_path)
    assert evidence["gate_f_complete"] is False
    assert evidence["ok"] is True
    assert evidence["portfolio"]["verdict"] in {"pass", "fail"}
    assert (tmp_path / "a11y_portfolio_drill.json").is_file()
