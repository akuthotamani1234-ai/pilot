from pathlib import Path

from backend.portfolio_artifact_manifest_drill import (
    run_portfolio_artifact_manifest_drill,
)


def test_portfolio_artifact_manifest_reports_honestly(tmp_path: Path):
    evidence = run_portfolio_artifact_manifest_drill(ops_dir=tmp_path)
    assert evidence["gate_f_complete"] is False
    assert (tmp_path / "portfolio_artifact_manifest_drill.json").is_file()
    # Reads from docs/ops-evidence regardless of ops_dir for source files.
    assert isinstance(evidence.get("ok"), bool)
    assert evidence.get("browsers") == ["chromium", "firefox", "webkit"]
