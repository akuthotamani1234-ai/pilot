"""Gate E controlled failure matrix stays incomplete and covers key categories."""
from pathlib import Path

from backend.failure_matrix import FIXTURES, build_failure_matrix, run_failure_matrix_drill


def test_failure_matrix_covers_expanded_taxonomy(tmp_path: Path):
    matrix = build_failure_matrix()
    assert matrix["gate_e_complete"] is False
    assert matrix["cases"] == len(FIXTURES)
    cats = set(matrix["counts"])
    for required in {
        "product_defect",
        "test_defect",
        "timeout",
        "flaky",
        "inconclusive",
        "infrastructure",
        "auth_problem",
        "test_data",
        "locator",
        "rule_violation",
    }:
        assert required in cats, f"missing category {required} in {cats}"
    by_id = {row["id"]: row["category"] for row in matrix["rows"]}
    assert by_id["session"] == "inconclusive"
    assert by_id["infra-block"] == "infrastructure"
    assert by_id["auth-login"] == "auth_problem"
    assert by_id["test-account"] == "test_data"
    assert by_id["locator-gone"] == "locator"
    assert by_id["rule-tag"] == "rule_violation"
    evidence = run_failure_matrix_drill(ops_dir=tmp_path)
    assert (tmp_path / "failure_matrix_drill.json").is_file()
    assert evidence["counts"] == matrix["counts"]
