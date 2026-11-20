"""Hosted on-call readiness pack stays incomplete for Gate H."""
from backend.hosted_oncall_readiness_pack_drill import (
    run_hosted_oncall_readiness_pack_drill,
)


def test_hosted_oncall_readiness_pack_stays_partial(tmp_path):
    evidence = run_hosted_oncall_readiness_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["live_hosted_paging"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "hosted_oncall_readiness_pack_drill.json").is_file()
