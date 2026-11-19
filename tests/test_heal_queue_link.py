"""A healing approval drill writes this install's evidence. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.healing_approval_queue_drill import run_healing_approval_queue_drill


def test_a_healing_approval_drill_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-heal-queue"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "healing_approval_queue.sqlite"
    kept.write_bytes(secret.encode())
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_healing_approval_queue_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_e_complete"] is False
    assert evidence["production_suite_executed"] is False
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "healing_approval_queue_drill.json").exists()

    real = tmp_path / "real"
    real.mkdir()
    saved = run_healing_approval_queue_drill(ops_dir=real)
    written = (real / "healing_approval_queue_drill.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_e_complete"] is False
    assert saved["first_auth_accepted"] is True
    assert "one auth locator repair" in written
    assert secret not in written
    assert kept.read_bytes() == original


def test_heal_queue_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-heal-queue-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "E")["status"] != "done"
    assert snap["complete"] is False
