"""A healing approval drill writes this install's evidence. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.healing_approval_queue_drill import run_healing_approval_queue_drill


def test_a_healing_approval_drill_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.approvals as approvals

    calls = {"n": 0}
    real_create = approvals.create

    def _create(*args, **kwargs):
        calls["n"] += 1
        return real_create(*args, **kwargs)

    monkeypatch.setattr(approvals, "create", _create)

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
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "healing_approval_queue_drill.json").exists()

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "healing_approval_queue_drill.json"
    planted.symlink_to(kept)
    skipped = run_healing_approval_queue_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    assert not (folder / "healing_approval_queue.sqlite").exists()
    planted.unlink()

    saved = run_healing_approval_queue_drill(ops_dir=folder)
    written = (folder / "healing_approval_queue_drill.json").read_text(encoding="utf-8")
    assert calls["n"] == 5
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
