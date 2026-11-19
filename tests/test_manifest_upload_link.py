"""Upload manifests write this install's receipt. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.device_artifact_manifest_drill import run_device_artifact_manifest_drill
from backend.portfolio_artifact_manifest_drill import (
    run_portfolio_artifact_manifest_drill,
)


def test_a_device_manifest_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.device_artifact_manifest_drill as mod

    calls = {"n": 0}
    real_sha = mod.hashlib.sha256

    def _sha256(data=b""):
        calls["n"] += 1
        return real_sha(data)

    monkeypatch.setattr(mod.hashlib, "sha256", _sha256)

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
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == ["device_artifact_manifest_drill.json"]

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "device_artifact_manifest_drill.json"
    planted.symlink_to(kept)
    skipped = run_device_artifact_manifest_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_device_artifact_manifest_drill(ops_dir=folder)
    written = (folder / "device_artifact_manifest_drill.json").read_text(encoding="utf-8")
    assert calls["n"] >= 1
    assert saved["gate_d_complete"] is False
    assert saved["api_levels"] == [24, 30, 34]
    assert secret not in written
    assert kept.read_bytes() == original


def test_a_portfolio_manifest_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.portfolio_artifact_manifest_drill as mod

    calls = {"n": 0}
    real_sha = mod.hashlib.sha256

    def _sha256(data=b""):
        calls["n"] += 1
        return real_sha(data)

    monkeypatch.setattr(mod.hashlib, "sha256", _sha256)

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
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == [
        "portfolio_artifact_manifest_drill.json",
    ]

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "portfolio_artifact_manifest_drill.json"
    planted.symlink_to(kept)
    skipped = run_portfolio_artifact_manifest_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_portfolio_artifact_manifest_drill(ops_dir=folder)
    written = (folder / "portfolio_artifact_manifest_drill.json").read_text(encoding="utf-8")
    assert calls["n"] >= 1
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
