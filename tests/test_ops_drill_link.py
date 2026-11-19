"""A backup drill writes this install's evidence. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.ops_drill import run_backup_restore_drill, run_local_load_probe, write_local_metrics_snapshot


def test_a_backup_drill_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    calls = {"n": 0}
    real_client = TestClient

    def _client(*args, **kwargs):
        calls["n"] += 1
        return real_client(*args, **kwargs)

    monkeypatch.setattr("fastapi.testclient.TestClient", _client)

    secret = "tenant-b-only-ops"
    other = tmp_path / "other"
    kept = other / "drill_src" / "keep.txt"
    kept.parent.mkdir(parents=True)
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_backup_restore_drill(ops_dir=linked)
    metrics = write_local_metrics_snapshot(ops_dir=linked)
    probe = run_local_load_probe(requests=4, ops_dir=linked)

    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert "link" in metrics["reason"]
    assert "link" in probe["reason"]
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "backup_restore_drill.json").exists()
    assert not (other / "local_metrics_snapshot.json").exists()
    assert not (other / "local_load_probe.json").exists()
    assert not (other / "drill_backup").exists()
    assert not (other / "drill_restore").exists()

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "local_load_probe.json"
    planted.symlink_to(kept)
    skipped = run_local_load_probe(requests=2, ops_dir=folder)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    probed = run_local_load_probe(requests=2, ops_dir=folder)
    assert probed["ok"] == 2
    assert calls["n"] == 1
    assert secret not in (folder / "local_load_probe.json").read_text(encoding="utf-8")

    metrics_link = folder / "local_metrics_snapshot.json"
    metrics_link.symlink_to(kept)
    refused_metrics = write_local_metrics_snapshot(ops_dir=folder)
    assert "link" in refused_metrics["reason"]
    assert refused_metrics["ok"] is False
    assert secret not in str(refused_metrics)
    assert kept.read_bytes() == original
    assert metrics_link.is_symlink()
    metrics_link.unlink()

    import backend.ops_drill as ops

    origin = ops.ROOT
    install = tmp_path / "install"
    (install / "artifacts").mkdir(parents=True)
    secret_db = other / "approvals.sqlite"
    secret_db.write_bytes(b"tenant-b-approvals-bytes")
    (install / "artifacts" / "approvals.sqlite").symlink_to(secret_db)
    workflow = install / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "blow-ai.yml").write_text("name: home\n", encoding="utf-8")
    monkeypatch.setattr(ops, "ROOT", install)
    recorded = write_local_metrics_snapshot(ops_dir=folder)
    recorded_text = metrics_link.read_text(encoding="utf-8")
    assert recorded["metrics"]["approvals_db_present"] is False
    assert recorded["metrics"]["ci_workflow_present"] is True
    assert "tenant-b-approvals-bytes" not in recorded_text
    assert secret not in recorded_text
    assert secret_db.read_bytes() == b"tenant-b-approvals-bytes"
    monkeypatch.setattr(ops, "ROOT", origin)

    saved = run_backup_restore_drill(ops_dir=folder)
    written = (folder / "backup_restore_drill.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert "gate-h-local" in written
    assert secret not in written
    assert kept.read_bytes() == original


def test_ops_drill_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-ops-drill-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
