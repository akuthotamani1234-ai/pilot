"""Gate H local drills never mark the gate complete."""
from backend.ops_drill import run_backup_restore_drill, run_local_load_probe, write_local_metrics_snapshot


def test_backup_restore_drill_writes_evidence(tmp_path):
    evidence = run_backup_restore_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "backup_restore_drill.json").is_file()
    metrics = write_local_metrics_snapshot(ops_dir=tmp_path)
    assert metrics["gate_h_complete"] is False
    assert (tmp_path / "local_metrics_snapshot.json").is_file()


def test_local_load_probe_writes_evidence(tmp_path):
    evidence = run_local_load_probe(requests=8, ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["ok"] == 8
    assert (tmp_path / "local_load_probe.json").is_file()
