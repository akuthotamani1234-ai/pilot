"""A backup drill writes this install's evidence. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.ops_drill import run_backup_restore_drill, run_local_load_probe, write_local_metrics_snapshot


def test_a_backup_drill_does_not_follow_a_link_into_another_folder(tmp_path):
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
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "backup_restore_drill.json").exists()
    assert not (other / "local_metrics_snapshot.json").exists()
    assert not (other / "local_load_probe.json").exists()
    assert not (other / "drill_backup").exists()
    assert not (other / "drill_restore").exists()

    real = tmp_path / "real"
    real.mkdir()
    saved = run_backup_restore_drill(ops_dir=real)
    written = (real / "backup_restore_drill.json").read_text(encoding="utf-8")
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
