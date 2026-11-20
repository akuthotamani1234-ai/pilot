"""A dispatch rehearsal stays in this install. A linked workflow is left unread."""
from backend.blueprint_progress import progress
from backend.hosted_dispatch_payload_rehearsal_drill import (
    run_hosted_dispatch_payload_rehearsal_drill,
)


def test_a_dispatch_rehearsal_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.hosted_dispatch_payload_rehearsal_drill as mod

    secret = "tenant-b-dispatch"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "hosted_dispatch_payload_rehearsal_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    foreign = tmp_path / "foreign.yml"
    foreign.write_text(secret, encoding="utf-8")
    linked_workflow = tmp_path / "linked.yml"
    linked_workflow.symlink_to(foreign)
    monkeypatch.setattr(mod, "ANDROID_WF", linked_workflow)
    monkeypatch.setattr(mod, "BROWSER_WF", linked_workflow)
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_hosted_dispatch_payload_rehearsal_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert refused["gate_f_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert foreign.read_text(encoding="utf-8") == secret
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_hosted_dispatch_payload_rehearsal_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    unread = run_hosted_dispatch_payload_rehearsal_drill(ops_dir=real)
    assert unread["ok"] is False
    assert unread["android"]["workflow_present"] is False
    assert unread["browsers"]["workflow_present"] is False
    assert secret not in str(unread)
    assert secret not in planted.read_text(encoding="utf-8")
    assert foreign.read_text(encoding="utf-8") == secret

    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "android-appium.yml").write_text("name: android\n", encoding="utf-8")
    (workflows / "browsers.yml").write_text("engines: chromium\n", encoding="utf-8")
    monkeypatch.setattr(mod, "ANDROID_WF", workflows / "android-appium.yml")
    monkeypatch.setattr(mod, "BROWSER_WF", workflows / "browsers.yml")
    saved = run_hosted_dispatch_payload_rehearsal_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert saved["android"]["payload"]["dispatched"] is False
    assert saved["ok"] is True
    assert "payloads rehearsed" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_dispatch_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-dispatch-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-dispatch-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert snap["complete"] is False
