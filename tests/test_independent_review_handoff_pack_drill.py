"""Independent review handoff pack stays unsigned for Gate G."""
from backend.independent_review_handoff_pack_drill import (
    run_independent_review_handoff_pack_drill,
)


def test_independent_review_handoff_pack_stays_partial(tmp_path, monkeypatch):
    import backend.independent_review_blocker_freeze_drill as freeze
    import backend.independent_review_findings_freeze_drill as findings
    import backend.independent_review_request_drill as req
    import backend.independent_review_response_sla_drill as sla
    import backend.independent_review_scope_matrix_drill as scope
    import backend.independent_review_signoff_pack_drill as sign
    import backend.independent_review_summary_drill as summary
    import backend.independent_reviewer_roster_contract_drill as roster

    monkeypatch.setattr(
        req, "run_independent_review_request_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False},
    )
    monkeypatch.setattr(
        sign, "run_independent_review_signoff_pack_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False},
    )
    monkeypatch.setattr(
        summary, "run_independent_review_summary_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False},
    )
    monkeypatch.setattr(
        scope, "run_independent_review_scope_matrix_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False},
    )
    monkeypatch.setattr(
        freeze, "run_independent_review_blocker_freeze_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False, "freeze_sha256": "abc"},
    )
    monkeypatch.setattr(
        sla, "run_independent_review_response_sla_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False},
    )
    monkeypatch.setattr(
        roster, "run_independent_reviewer_roster_contract_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False},
    )
    monkeypatch.setattr(
        findings, "run_independent_review_findings_freeze_drill",
        lambda ops_dir=None: {"ok": True, "signed_off": False},
    )
    evidence = run_independent_review_handoff_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "independent_review_handoff_pack_drill.json").is_file()
