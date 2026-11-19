"""Independent review findings template stays unsigned for Gate G."""
from backend.independent_review_findings_template_drill import (
    run_independent_review_findings_template_drill,
)


def test_independent_review_findings_template_stays_partial(tmp_path):
    evidence = run_independent_review_findings_template_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "independent_review_findings_template_drill.json").is_file()
    assert (tmp_path / "INDEPENDENT_REVIEW_FINDINGS.md").is_file()
