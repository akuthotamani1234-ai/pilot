"""Hosted CI artifact gate pack stays incomplete for Gates D/F."""
from backend.hosted_ci_artifact_gate_pack_drill import (
    run_hosted_ci_artifact_gate_pack_drill,
)


def test_hosted_ci_artifact_gate_pack_stays_partial(tmp_path, monkeypatch):
    import backend.ci_artifact_upload_rehearsal_drill as upload
    import backend.hosted_dispatch_payload_rehearsal_drill as dispatch
    import backend.hosted_runner_readiness_drill as ready

    monkeypatch.setattr(
        ready, "run_hosted_runner_readiness_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        dispatch, "run_hosted_dispatch_payload_rehearsal_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        upload, "run_ci_artifact_upload_rehearsal_drill",
        lambda ops_dir=None: {"ok": True},
    )
    evidence = run_hosted_ci_artifact_gate_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["live_hosted_runners"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "hosted_ci_artifact_gate_pack_drill.json").is_file()
