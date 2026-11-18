"""Gate F security portfolio drill stays incomplete and never probes."""
from pathlib import Path

from backend.security_portfolio_drill import run_security_portfolio_drill


def test_security_portfolio_drill_is_passive(tmp_path: Path):
    evidence = run_security_portfolio_drill(ops_dir=tmp_path)
    assert evidence["gate_f_complete"] is False
    assert evidence["probe"] is False
    assert evidence["portfolio"]["probe"] is False
    assert evidence["ok"] is True  # observations present (may fail missing headers)
    assert (tmp_path / "security_portfolio_drill.json").is_file()
