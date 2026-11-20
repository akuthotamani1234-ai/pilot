"""Independent review sign-off pack stays unsigned for Gate G."""
from backend.independent_review_signoff_pack_drill import (
    run_independent_review_signoff_pack_drill,
)


def test_independent_review_signoff_pack_stays_partial(tmp_path, monkeypatch):
    import backend.independent_review_attestation_drill as attest
    import backend.independent_review_evidence_catalog_drill as cat
    import backend.independent_review_integrity_drill as integ

    monkeypatch.setattr(
        cat, "run_independent_review_evidence_catalog_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False, "entry_count": 21},
    )
    monkeypatch.setattr(
        integ, "run_independent_review_integrity_drill",
        lambda ops_dir=None: {
            "ok": True, "signed_off": False, "integrity_sha256": "abc",
        },
    )
    monkeypatch.setattr(
        attest, "run_independent_review_attestation_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False},
    )
    evidence = run_independent_review_signoff_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "independent_review_signoff_pack_drill.json").is_file()
