"""Hosted CI artifact retention contract stays incomplete for Gates D/F."""
from backend.hosted_ci_artifact_retention_contract_drill import (
    ANDROID_ARTIFACTS,
    BROWSER_ARTIFACTS,
    run_hosted_ci_artifact_retention_contract_drill,
)


def test_hosted_ci_artifact_retention_contract_stays_partial(tmp_path, monkeypatch):
    import backend.hosted_ci_artifact_retention_contract_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in (*ANDROID_ARTIFACTS, *BROWSER_ARTIFACTS):
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_hosted_ci_artifact_retention_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["live_hosted_runners"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "hosted_ci_artifact_retention_contract_drill.json").is_file()
