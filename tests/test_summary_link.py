"""A review summary writes this install's notes. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.independent_review_summary_drill import (
    run_independent_review_summary_drill,
)


def test_a_review_summary_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-summary"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "INDEPENDENT_REVIEW_SUMMARY.md"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_independent_review_summary_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == ["INDEPENDENT_REVIEW_SUMMARY.md"]

    real = tmp_path / "real"
    real.mkdir()
    saved = run_independent_review_summary_drill(ops_dir=real)
    written = (real / "INDEPENDENT_REVIEW_SUMMARY.md").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert "not" in written and "sign-off" in written
    assert secret not in written
    assert kept.read_bytes() == original


def test_summary_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-summary-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
