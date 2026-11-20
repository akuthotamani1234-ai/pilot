"""A runner contract stays in this install. A link is not counted as a workflow."""
from backend.blueprint_progress import progress
from backend.hosted_runner_contract_drill import run_hosted_runner_contract_drill


def test_a_runner_contract_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.hosted_runner_contract_drill as mod

    secret = "tenant-b-runner"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "multi_browser_ci_contract.json"
    kept_device = other / "multi_device_ci_contract.json"
    kept.write_text(secret, encoding="utf-8")
    kept_device.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    original_device = kept_device.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_hosted_runner_contract_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert refused["gate_f_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert kept_device.read_bytes() == original_device

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_hosted_runner_contract_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    assert not (real / kept_device.name).exists()
    planted.unlink()

    real_root = mod.ROOT
    linked_root = tmp_path / "root"
    workflows = linked_root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    foreign_browser = other / "browser.yml"
    foreign_device = other / "device.yml"
    foreign_browser.write_text(secret, encoding="utf-8")
    foreign_device.write_text(secret, encoding="utf-8")
    (workflows / "multi-browser-portfolios.yml").symlink_to(foreign_browser)
    (workflows / "android-appium.yml").symlink_to(foreign_device)
    monkeypatch.setattr(mod, "ROOT", linked_root)
    unread = run_hosted_runner_contract_drill(ops_dir=real)
    unread_text = (real / kept.name).read_text(encoding="utf-8")
    assert unread["ok"] is False
    assert unread["multi_browser"]["workflow_exists"] is False
    assert unread["multi_device"]["workflow_exists"] is False
    assert secret not in str(unread)
    assert secret not in unread_text
    assert foreign_browser.read_text(encoding="utf-8") == secret
    assert foreign_device.read_text(encoding="utf-8") == secret
    monkeypatch.setattr(mod, "ROOT", real_root)

    saved = run_hosted_runner_contract_drill(ops_dir=real)
    saved_text = (real / kept.name).read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert saved["ok"] is True
    assert saved["multi_browser"]["workflow_exists"] is True
    assert saved["multi_device"]["workflow_exists"] is True
    assert "Hosted runner contracts" in saved["reason"]
    assert "Offline CI contract" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original
    assert kept_device.read_bytes() == original_device


def test_runner_contract_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-runner-contract-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-runner-contract-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert snap["complete"] is False
