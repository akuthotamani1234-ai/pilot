"""Independent review findings freeze stays unsigned for Gate G."""
from backend.independent_review_findings_freeze_drill import (
    run_independent_review_findings_freeze_drill,
)


def test_independent_review_findings_freeze_stays_partial(tmp_path, monkeypatch):
    import backend.independent_review_blocker_freeze_drill as freeze
    import backend.independent_review_findings_freeze_drill as mod

    findings = tmp_path / "docs" / "ops-evidence" / "INDEPENDENT_REVIEW_FINDINGS.md"
    findings.parent.mkdir(parents=True)
    findings.write_text("# Findings\n", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "FINDINGS", findings)
    monkeypatch.setattr(
        freeze, "run_independent_review_blocker_freeze_drill",
        lambda ops_dir=None: {
            "ok": True,
            "signed_off": False,
            "freeze_sha256": "abc123",
            "freeze": {"open_count": 6},
        },
    )
    evidence = run_independent_review_findings_freeze_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert evidence["findings_present"] is True
    assert (tmp_path / "independent_review_findings_freeze_drill.json").is_file()
