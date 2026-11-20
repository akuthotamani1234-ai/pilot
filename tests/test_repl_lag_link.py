"""A replication lag contract stays in this install. A link is left unread."""
from backend.blueprint_progress import progress
from backend.dual_region_replication_lag_contract_drill import (
    LOCAL_PARTIAL,
    run_dual_region_replication_lag_contract_drill,
)


def test_a_replication_lag_contract_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.dual_region_replication_lag_contract_drill as mod

    secret = "tenant-b-repl"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "dual_region_replication_lag_contract_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_dual_region_replication_lag_contract_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_dual_region_replication_lag_contract_drill(ops_dir=real)
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
    unread = run_dual_region_replication_lag_contract_drill(ops_dir=real)
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
    saved = run_dual_region_replication_lag_contract_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["live_hosted_dr"] is False
    assert saved["ok"] is True
    assert saved["contract"]["max_lag_seconds"] == 30
    assert "replication lag contract recorded" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_repl_lag_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-repl-lag-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-repl-lag-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
