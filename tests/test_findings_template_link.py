"""A findings template writes this install's notes. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.independent_review_findings_template_drill import (
    run_independent_review_findings_template_drill,
)


def test_a_findings_template_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-findings"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "INDEPENDENT_REVIEW_FINDINGS.md"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_independent_review_findings_template_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "independent_review_findings_template_drill.json").exists()

    real = tmp_path / "real"
    real.mkdir()
    saved = run_independent_review_findings_template_drill(ops_dir=real)
    written = (real / "INDEPENDENT_REVIEW_FINDINGS.md").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert "not signed" in written
    assert secret not in written
    assert kept.read_bytes() == original


def test_findings_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-findings-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
