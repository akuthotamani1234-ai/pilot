"""A workflow contract writes this install's evidence. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.workflow_dispatch_contract_drill import run_workflow_dispatch_contract_drill


def test_a_workflow_contract_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.workflow_dispatch_contract_drill as mod

    calls = {"n": 0}
    real_checks = mod._checks

    def _checks(*args, **kwargs):
        calls["n"] += 1
        return real_checks(*args, **kwargs)

    monkeypatch.setattr(mod, "_checks", _checks)

    secret = "tenant-b-only-workflow"
    other = tmp_path / "other"
    kept = other / "keep.txt"
    other.mkdir()
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_workflow_dispatch_contract_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "workflow_dispatch_contract_drill.json").exists()

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "workflow_dispatch_contract_drill.json"
    planted.symlink_to(kept)
    skipped = run_workflow_dispatch_contract_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_workflow_dispatch_contract_drill(ops_dir=folder)
    written = (folder / "workflow_dispatch_contract_drill.json").read_text(encoding="utf-8")
    assert calls["n"] == 2
    assert saved["ok"] is True
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert "workflow_dispatch" in written
    assert secret not in written
    assert kept.read_bytes() == original


def test_workflow_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-workflow-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
