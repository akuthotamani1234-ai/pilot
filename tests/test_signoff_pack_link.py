"""A sign-off pack stays in this install. A link does not start the bundled checks."""
from backend.blueprint_progress import progress
from backend.independent_review_signoff_pack_drill import (
    run_independent_review_signoff_pack_drill,
)


def test_a_signoff_pack_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.independent_review_attestation_drill as attest
    import backend.independent_review_evidence_catalog_drill as cat
    import backend.independent_review_integrity_drill as integ

    calls = {"n": 0}

    def _pass(**_kwargs):
        calls["n"] += 1
        return {"ok": True, "signed_off": False}

    monkeypatch.setattr(cat, "run_independent_review_evidence_catalog_drill", _pass)
    monkeypatch.setattr(integ, "run_independent_review_integrity_drill", _pass)
    monkeypatch.setattr(attest, "run_independent_review_attestation_drill", _pass)

    secret = "tenant-b-signoff"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "independent_review_signoff_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_independent_review_signoff_pack_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_g_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_independent_review_signoff_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_independent_review_signoff_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert saved["ok"] is True
    assert saved["parts"]["catalog"] is True
    assert calls["n"] == 3
    assert "sign-off pack ok" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_signoff_pack_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-signoff-pack-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-signoff-pack-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
