"""Independent review attestation stays unsigned for Gate G."""
from backend.independent_review_attestation_drill import (
    run_independent_review_attestation_drill,
)


def test_independent_review_attestation_stays_partial(tmp_path, monkeypatch):
    import backend.independent_review_evidence_catalog_drill as cat
    import backend.independent_review_integrity_drill as integ

    monkeypatch.setattr(
        integ,
        "run_independent_review_integrity_drill",
        lambda ops_dir=None: {
            "ok": True,
            "signed_off": False,
            "integrity_sha256": "abc123",
        },
    )
    monkeypatch.setattr(
        cat,
        "run_independent_review_evidence_catalog_drill",
        lambda ops_dir=None: {"ok": True, "entry_count": 21},
    )
    evidence = run_independent_review_attestation_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["attestation"]["verdict"] == "pending"
    assert evidence["attestation"]["integrity_sha256"] == "abc123"
    assert evidence["ok"] is True
    assert (tmp_path / "independent_review_attestation_drill.json").is_file()
