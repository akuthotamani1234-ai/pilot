"""Hosted DR communications contract stays incomplete for Gate H."""
from backend.hosted_dr_comms_contract_drill import (
    LOCAL_PARTIAL,
    run_hosted_dr_comms_contract_drill,
)


def test_hosted_dr_comms_contract_stays_partial(tmp_path, monkeypatch):
    import backend.hosted_dr_comms_contract_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in LOCAL_PARTIAL:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_hosted_dr_comms_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["live_hosted_dr"] is False
    assert evidence["ok"] is True
    assert "status_page" in evidence["contract"]["channels"]
    assert (tmp_path / "hosted_dr_comms_contract_drill.json").is_file()
