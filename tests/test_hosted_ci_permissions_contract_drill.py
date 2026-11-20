"""Hosted CI permissions contract stays incomplete for Gates D/F."""
from backend.hosted_ci_permissions_contract_drill import (
    run_hosted_ci_permissions_contract_drill,
)


def test_hosted_ci_permissions_contract_stays_partial(tmp_path):
    evidence = run_hosted_ci_permissions_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["live_hosted_runners"] is False
    assert evidence["ok"] is True
    assert evidence["android"]["checks"]["contents_read"] is True
    assert evidence["browsers"]["checks"]["contents_read"] is True
    assert (tmp_path / "hosted_ci_permissions_contract_drill.json").is_file()
