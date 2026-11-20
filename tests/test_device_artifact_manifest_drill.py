from pathlib import Path

from backend.device_artifact_manifest_drill import run_device_artifact_manifest_drill


def test_device_artifact_manifest_reports_honestly(tmp_path: Path):
    evidence = run_device_artifact_manifest_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert (tmp_path / "device_artifact_manifest_drill.json").is_file()
    assert isinstance(evidence.get("ok"), bool)
    assert evidence.get("api_levels") == [24, 30, 34]
