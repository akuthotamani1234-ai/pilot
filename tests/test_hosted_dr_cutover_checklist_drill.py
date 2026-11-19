"""Hosted DR cutover checklist stays incomplete for Gate H."""
from backend.hosted_dr_cutover_checklist_drill import (
    CHECKLIST,
    run_hosted_dr_cutover_checklist_drill,
)


def test_hosted_dr_cutover_checklist_stays_partial(tmp_path, monkeypatch):
    import backend.hosted_dr_cutover_checklist_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for _, artifact, _ in CHECKLIST:
        (ops / artifact).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_hosted_dr_cutover_checklist_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["live_hosted_dr"] is False
    assert evidence["ok"] is True
    assert evidence["score_of"] == len(CHECKLIST)
    assert (tmp_path / "hosted_dr_cutover_checklist_drill.json").is_file()
