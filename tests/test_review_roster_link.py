"""A reviewer roster stays in this install. A link is left unread."""
from backend.blueprint_progress import progress
from backend.independent_reviewer_roster_contract_drill import (
    LOCAL_PARTIAL,
    run_independent_reviewer_roster_contract_drill,
)


def test_a_reviewer_roster_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.independent_reviewer_roster_contract_drill as mod

    secret = "tenant-b-roster"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "independent_reviewer_roster_contract_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_independent_reviewer_roster_contract_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_g_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_independent_reviewer_roster_contract_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / LOCAL_PARTIAL[0]).write_text(secret, encoding="utf-8")
    linked_root = tmp_path / "linked-root"
    (linked_root / "docs").mkdir(parents=True)
    (linked_root / "docs" / "ops-evidence").symlink_to(foreign, target_is_directory=True)
    monkeypatch.setattr(mod, "ROOT", linked_root)
    unread = run_independent_reviewer_roster_contract_drill(ops_dir=real)
    assert unread["ok"] is False
    assert unread["local_partial_present"] == []
    assert secret not in str(unread)
    assert secret not in planted.read_text(encoding="utf-8")
    assert (foreign / LOCAL_PARTIAL[0]).read_text(encoding="utf-8") == secret

    real_root = tmp_path / "real-root"
    ops = real_root / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in LOCAL_PARTIAL:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", real_root)
    saved = run_independent_reviewer_roster_contract_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert saved["ok"] is True
    assert len(saved["roles"]) == 4
    assert "reviewer roster contract recorded" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_review_roster_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-review-roster-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-review-roster-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
