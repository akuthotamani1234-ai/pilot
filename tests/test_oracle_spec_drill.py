"""Gate C oracle-spec drill stays incomplete and blocks AI defects."""
from pathlib import Path

from backend.oracle_spec_drill import run_oracle_spec_drill


def test_oracle_spec_drill_binds_fixture_and_blocks_ai(tmp_path: Path):
    evidence = run_oracle_spec_drill(ops_dir=tmp_path)
    assert evidence["gate_c_complete"] is False
    assert evidence["ok"] is True
    assert evidence["features_bound"] >= 1
    assert all(row["accepted"] for row in evidence["approved_cases"])
    assert evidence["ai_proposal"]["decide_verdict"] == "needs_review"
    assert evidence["ai_proposal"]["softened_category"] == "inconclusive"
    assert evidence["business_rule"]["pass_verdict"] == "pass"
    assert evidence["business_rule"]["fail_verdict"] == "fail"
    assert (tmp_path / "oracle_spec_drill.json").is_file()
