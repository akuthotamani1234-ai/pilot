from pathlib import Path

from backend.independent_review_readiness_drill import (
    run_independent_review_readiness_drill,
)


def test_independent_review_readiness_stays_unsigned(tmp_path: Path):
    evidence = run_independent_review_readiness_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert (tmp_path / "independent_review_readiness_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("score") == evidence.get("score_of")
