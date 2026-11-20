"""An evidence catalog lists this install's files. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.independent_review_evidence_catalog_drill import (
    run_independent_review_evidence_catalog_drill,
)


def test_an_evidence_catalog_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-catalog"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "tenant-b-only-catalog.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_independent_review_evidence_catalog_drill(ops_dir=linked)
    dumped = str(evidence)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert kept.read_bytes() == original
    assert secret not in dumped
    assert "tenant-b-only-catalog.json" not in dumped
    assert [path.name for path in other.iterdir()] == ["tenant-b-only-catalog.json"]

    real = tmp_path / "real"
    real.mkdir()
    (real / "this-install.json").write_text("this-install", encoding="utf-8")
    leaked = real / "leaked.json"
    leaked.symlink_to(kept)
    saved = run_independent_review_evidence_catalog_drill(ops_dir=real)
    written = (real / "independent_review_evidence_catalog_drill.json").read_text(encoding="utf-8")
    names = {row["name"] for row in saved["entries"]}
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert "this-install.json" in names
    assert "leaked.json" not in names
    assert secret not in written
    assert kept.read_bytes() == original


def test_catalog_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-catalog-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
