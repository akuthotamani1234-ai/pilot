"""Independent review request receipt stays unsigned."""
from backend.independent_review_request_drill import run_independent_review_request_drill


def test_independent_review_request_stays_unsigned(tmp_path):
    evidence = run_independent_review_request_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert evidence["request"]["open_blockers"]
    assert (tmp_path / "independent_review_request_drill.json").is_file()
