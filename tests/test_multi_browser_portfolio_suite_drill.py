"""Gate F multi-browser suite stays incomplete."""
from pathlib import Path

from backend.multi_browser_portfolio_suite_drill import (
    run_multi_browser_portfolio_suite_drill,
)


def test_multi_browser_portfolio_suite_drill_reports_honestly(tmp_path: Path):
    evidence = run_multi_browser_portfolio_suite_drill(ops_dir=tmp_path)
    assert evidence["gate_f_complete"] is False
    assert (tmp_path / "multi_browser_portfolio_suite_drill.json").is_file()
    # Engines may be missing on some runners; when all three are present, ok is True.
    if len(evidence.get("browsers") or []) >= 3:
        assert evidence.get("ok") is True
        assert int(evidence.get("suites_passed") or 0) == int(evidence.get("suites_total") or 0)
    else:
        assert evidence.get("reason")
