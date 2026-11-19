"""Paging severity routing contract stays incomplete for Gate H."""
from backend.paging_severity_routing_contract_drill import (
    LOCAL_PARTIAL,
    run_paging_severity_routing_contract_drill,
)


def test_paging_severity_routing_contract_stays_partial(tmp_path, monkeypatch):
    import backend.paging_severity_routing_contract_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in LOCAL_PARTIAL:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_paging_severity_routing_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["live_hosted_paging"] is False
    assert evidence["ok"] is True
    assert any(r["severity"] == "SEV1" for r in evidence["routes"])
    assert (tmp_path / "paging_severity_routing_contract_drill.json").is_file()
