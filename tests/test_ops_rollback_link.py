"""A rollback rehearsal writes this install's evidence. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.ops_rollback_drill import run_ci_rollback_rehearsal


def test_a_rollback_rehearsal_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-rollback"
    other = tmp_path / "other"
    kept = other / "rollback_good" / "keep.txt"
    kept.parent.mkdir(parents=True)
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_ci_rollback_rehearsal(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_h_complete"] is False
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "ci_rollback_rehearsal.json").exists()
    assert not (other / "rollback_bad").exists()
    assert not (other / "rollback_restored").exists()

    real = tmp_path / "real"
    real.mkdir()
    saved = run_ci_rollback_rehearsal(ops_dir=real)
    written = (real / "rollback_restored" / "artifact.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_h_complete"] is False
    assert "known_good" in written
    assert secret not in written
    assert kept.read_bytes() == original


def test_rollback_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-rollback-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
