"""Hosted dispatch payload rehearsal stays incomplete for Gates D/F."""
from backend.hosted_dispatch_payload_rehearsal_drill import (
    run_hosted_dispatch_payload_rehearsal_drill,
)


def test_hosted_dispatch_payload_rehearsal_stays_partial(tmp_path):
    evidence = run_hosted_dispatch_payload_rehearsal_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["android"]["payload"]["dispatched"] is False
    assert evidence["browsers"]["payload"]["dispatched"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "hosted_dispatch_payload_rehearsal_drill.json").is_file()
