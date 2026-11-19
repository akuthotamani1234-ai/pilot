"""CI artifact upload rehearsal stays incomplete for Gates D/F."""
from backend.ci_artifact_upload_rehearsal_drill import (
    run_ci_artifact_upload_rehearsal_drill,
)


def test_ci_artifact_upload_rehearsal_stays_partial(tmp_path):
    evidence = run_ci_artifact_upload_rehearsal_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    # Staging copies from repo ops-evidence; ok when those files exist.
    assert evidence["android"]["artifacts"] or evidence["android"]["missing"] is not None
    assert (tmp_path / "ci_artifact_upload_rehearsal_drill.json").is_file()
    assert (tmp_path / "ci-upload-rehearsal").is_dir()
