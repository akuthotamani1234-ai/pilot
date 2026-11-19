"""Upload manifests write this install's receipt. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.device_artifact_manifest_drill import run_device_artifact_manifest_drill
from backend.portfolio_artifact_manifest_drill import (
    run_portfolio_artifact_manifest_drill,
)


def test_a_device_manifest_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-device-manifest"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "device_artifact_manifest_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_device_artifact_manifest_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_d_complete"] is False
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == ["device_artifact_manifest_drill.json"]

    real = tmp_path / "real"
    real.mkdir()
    saved = run_device_artifact_manifest_drill(ops_dir=real)
    written = (real / "device_artifact_manifest_drill.json").read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["api_levels"] == [24, 30, 34]
    assert secret not in written
    assert kept.read_bytes() == original


def test_a_portfolio_manifest_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-portfolio-manifest"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "portfolio_artifact_manifest_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_portfolio_artifact_manifest_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_f_complete"] is False
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == [
        "portfolio_artifact_manifest_drill.json",
    ]

    real = tmp_path / "real"
    real.mkdir()
    saved = run_portfolio_artifact_manifest_drill(ops_dir=real)
    written = (real / "portfolio_artifact_manifest_drill.json").read_text(encoding="utf-8")
    assert saved["gate_f_complete"] is False
    assert saved["browsers"] == ["chromium", "firefox", "webkit"]
    assert secret not in written
    assert kept.read_bytes() == original


def test_manifest_upload_links_stay_on_the_sidebar():
    snap = progress()
    device = next(item for item in snap["upcoming"] if item["id"] == "G-device-manifest-link")
    portfolio = next(
        item for item in snap["upcoming"] if item["id"] == "G-portfolio-manifest-link"
    )
    assert device["status"] == "done"
    assert portfolio["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
