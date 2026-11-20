"""An attestation writes this install's stub. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.independent_review_attestation_drill import (
    run_independent_review_attestation_drill,
)


def test_an_attestation_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.independent_review_evidence_catalog_drill as cat
    import backend.independent_review_integrity_drill as integ

    calls = {"n": 0}

    def _catalog(ops_dir=None):
        calls["n"] += 1
        return {"ok": True, "entry_count": 21, "signed_off": False}

    def _integrity(ops_dir=None):
        calls["n"] += 1
        return {
            "ok": True,
            "signed_off": False,
            "integrity_sha256": "this-install-hash",
        }

    monkeypatch.setattr(cat, "run_independent_review_evidence_catalog_drill", _catalog)
    monkeypatch.setattr(integ, "run_independent_review_integrity_drill", _integrity)

    secret = "tenant-b-only-attestation"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "independent_review_attestation_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_independent_review_attestation_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == [
        "independent_review_attestation_drill.json",
    ]

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "independent_review_attestation_drill.json"
    planted.symlink_to(kept)
    skipped = run_independent_review_attestation_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert skipped["signed_off"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_independent_review_attestation_drill(ops_dir=folder)
    written = (folder / "independent_review_attestation_drill.json").read_text(encoding="utf-8")
    assert calls["n"] == 2
    assert saved["ok"] is True
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert saved["attestation"]["verdict"] == "pending"
    assert saved["attestation"]["integrity_sha256"] == "this-install-hash"
    assert secret not in written
    assert kept.read_bytes() == original


def test_attestation_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-attestation-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
