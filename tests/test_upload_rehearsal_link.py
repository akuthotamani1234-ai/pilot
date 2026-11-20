"""An upload rehearsal writes this install's evidence. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.ci_artifact_upload_rehearsal_drill import run_ci_artifact_upload_rehearsal_drill


def test_an_upload_rehearsal_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.workflow_dispatch_contract_drill as contracts

    calls = {"n": 0}
    real_contract = contracts.run_workflow_dispatch_contract_drill

    def _contract(*args, **kwargs):
        calls["n"] += 1
        return real_contract(*args, **kwargs)

    monkeypatch.setattr(contracts, "run_workflow_dispatch_contract_drill", _contract)

    secret = "tenant-b-only-upload"
    other = tmp_path / "other"
    kept = other / "ci-upload-rehearsal" / "keep.txt"
    kept.parent.mkdir(parents=True)
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_ci_artifact_upload_rehearsal_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "ci_artifact_upload_rehearsal_drill.json").exists()
    assert not (other / "workflow_dispatch_contract_drill.json").exists()

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "ci_artifact_upload_rehearsal_drill.json"
    planted.symlink_to(kept)
    skipped = run_ci_artifact_upload_rehearsal_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    assert not (folder / "ci-upload-rehearsal").exists()
    planted.unlink()

    saved = run_ci_artifact_upload_rehearsal_drill(ops_dir=folder)
    written = (folder / "ci_artifact_upload_rehearsal_drill.json").read_text(encoding="utf-8")
    assert calls["n"] == 1
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert "ci_artifact_upload_rehearsal" in written
    assert secret not in written
    assert kept.read_bytes() == original


def test_upload_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-upload-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
