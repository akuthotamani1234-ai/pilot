"""A review handoff stays in this install. A link is left unwritten."""
from backend.blueprint_progress import progress
from backend.independent_review_handoff_pack_drill import (
    run_independent_review_handoff_pack_drill,
)


def test_a_review_handoff_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.independent_review_blocker_freeze_drill as freeze
    import backend.independent_review_findings_freeze_drill as findings
    import backend.independent_review_request_drill as req
    import backend.independent_review_response_sla_drill as sla
    import backend.independent_review_scope_matrix_drill as scope
    import backend.independent_review_signoff_pack_drill as sign
    import backend.independent_review_summary_drill as summary
    import backend.independent_reviewer_roster_contract_drill as roster

    calls = {"n": 0}

    def _pass(**_kwargs):
        calls["n"] += 1
        return {"ok": True, "signed_off": False}

    for module, name in (
        (req, "run_independent_review_request_drill"),
        (sign, "run_independent_review_signoff_pack_drill"),
        (summary, "run_independent_review_summary_drill"),
        (scope, "run_independent_review_scope_matrix_drill"),
        (freeze, "run_independent_review_blocker_freeze_drill"),
        (sla, "run_independent_review_response_sla_drill"),
        (roster, "run_independent_reviewer_roster_contract_drill"),
        (findings, "run_independent_review_findings_freeze_drill"),
    ):
        monkeypatch.setattr(module, name, _pass)

    secret = "tenant-b-handoff"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "independent_review_handoff_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_independent_review_handoff_pack_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_g_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]
    assert calls["n"] == 0

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_independent_review_handoff_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    assert calls["n"] == 0
    planted.unlink()

    saved = run_independent_review_handoff_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert saved["ok"] is True
    assert saved["parts"]["request"] is True
    assert calls["n"] == 8
    assert "handoff pack ok" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_review_handoff_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-review-handoff-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-review-handoff-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
