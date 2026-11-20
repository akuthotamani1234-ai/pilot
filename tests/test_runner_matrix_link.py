"""A runner matrix stays in this install. A link does not start the bundled checks."""
from backend.blueprint_progress import progress
from backend.hosted_ci_runner_matrix_drill import run_hosted_ci_runner_matrix_drill


def test_a_runner_matrix_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.device_artifact_manifest_drill as devices
    import backend.hosted_ci_runner_matrix_drill as mod
    import backend.hosted_runner_contract_drill as contracts
    import backend.portfolio_artifact_manifest_drill as portfolios

    calls = {"n": 0}

    def _pass(**_kwargs):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(contracts, "run_hosted_runner_contract_drill", _pass)
    monkeypatch.setattr(devices, "run_device_artifact_manifest_drill", _pass)
    monkeypatch.setattr(portfolios, "run_portfolio_artifact_manifest_drill", _pass)

    secret = "tenant-b-matrix"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "hosted_ci_runner_matrix_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_hosted_ci_runner_matrix_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert refused["gate_f_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_hosted_ci_runner_matrix_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    foreign = tmp_path / "foreign-workflows"
    foreign.mkdir()
    (foreign / "android-appium.yml").write_text(secret, encoding="utf-8")
    (foreign / "multi-browser-portfolios.yml").write_text(secret, encoding="utf-8")
    linked_root = tmp_path / "linked-root"
    linked_root.mkdir()
    (linked_root / ".github").mkdir()
    (linked_root / ".github" / "workflows").symlink_to(foreign, target_is_directory=True)
    monkeypatch.setattr(mod, "ROOT", linked_root)
    unread = run_hosted_ci_runner_matrix_drill(ops_dir=real)
    assert unread["ok"] is False
    assert unread["matrix"]["multi_device"]["workflow_exists"] is False
    assert unread["matrix"]["multi_browser"]["workflow_exists"] is False
    assert calls["n"] == 3
    assert secret not in str(unread)
    assert secret not in planted.read_text(encoding="utf-8")
    assert (foreign / "android-appium.yml").read_text(encoding="utf-8") == secret

    real_root = tmp_path / "real-root"
    workflows = real_root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "android-appium.yml").write_text("name: android\n", encoding="utf-8")
    (workflows / "multi-browser-portfolios.yml").write_text(
        "name: browsers\n", encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", real_root)
    saved = run_hosted_ci_runner_matrix_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert saved["ok"] is True
    assert saved["matrix"]["multi_device"]["api_levels"] == [24, 30, 34]
    assert calls["n"] == 6
    assert "runner matrix snapshot recorded" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_runner_matrix_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-runner-matrix-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-runner-matrix-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert snap["complete"] is False
