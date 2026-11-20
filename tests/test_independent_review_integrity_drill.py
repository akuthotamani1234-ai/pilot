"""Independent review integrity receipt stays unsigned."""
from backend.independent_review_integrity_drill import (
    run_independent_review_integrity_drill,
)


def test_independent_review_integrity_stays_unsigned(tmp_path):
    evidence = run_independent_review_integrity_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["integrity_sha256"]
    assert (tmp_path / "independent_review_integrity_drill.json").is_file()
