"""Gate F performance portfolio drill stays incomplete."""
from pathlib import Path

from backend.perf_portfolio_drill import run_perf_portfolio_drill


def test_perf_portfolio_drill_has_timings(tmp_path: Path):
    evidence = run_perf_portfolio_drill(ops_dir=tmp_path)
    assert evidence["gate_f_complete"] is False
    assert evidence["ok"] is True
    assert evidence["timings"]["samples"] >= 3
    assert evidence["portfolio"]["verdict"] in {"pass", "fail"}
    assert (tmp_path / "perf_portfolio_drill.json").is_file()
