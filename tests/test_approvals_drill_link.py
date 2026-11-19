"""An approvals drill writes this install's queue. A link is left untouched."""
from backend.approvals_drill import run_approvals_drill
from backend.blueprint_progress import progress


def test_an_approvals_drill_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-approvals"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "keep.txt"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_approvals_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_i_complete"] is False
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "approvals_work").exists()
    assert not (other / "approvals_drill.json").exists()

    real = tmp_path / "real"
    real.mkdir()
    saved = run_approvals_drill(ops_dir=real)
    written = (real / "approvals_drill.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_i_complete"] is False
    assert saved["accepted_status"] == "accepted"
    assert "approvals_enqueue_decide" in written
    assert secret not in written
    assert kept.read_bytes() == original


def test_approvals_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-approvals-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "I")["status"] != "done"
    assert snap["complete"] is False
