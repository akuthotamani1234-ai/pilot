"""A runner audit reads this install's inputs. A link is left unread."""
from backend.blueprint_progress import progress
from backend.hosted_workflow_runner_audit_drill import (
    run_hosted_workflow_runner_audit_drill,
)


def test_a_runner_audit_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.hosted_workflow_runner_audit_drill as mod

    secret = "tenant-b-only-runner-audit"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "hosted_workflow_runner_audit_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_hosted_workflow_runner_audit_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert refused["gate_f_complete"] is False
    assert refused["live_hosted_runners"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    secret_yaml = other / "secret-workflow.yml"
    secret_yaml.write_text(
        f"# {secret}\non:\n  workflow_dispatch:\n    inputs:\n      api_level: {secret}\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/upload-artifact@v4\n",
        encoding="utf-8",
    )
    android_link = tmp_path / "android-link.yml"
    android_link.symlink_to(secret_yaml)
    monkeypatch.setattr(mod, "ANDROID_WF", android_link)
    real = tmp_path / "real"
    real.mkdir()
    skipped = run_hosted_workflow_runner_audit_drill(ops_dir=real)
    written = (real / kept.name).read_text(encoding="utf-8")
    assert skipped["android"]["checks"]["present"] is False
    assert skipped["android"]["required_inputs"]["api_level"] is False
    assert skipped["android"]["checks"]["upload_artifact"] is False
    assert secret not in written
    assert kept.read_bytes() == original

    own = tmp_path / "own-android.yml"
    own.write_text(
        "on:\n  workflow_dispatch:\n    inputs:\n"
        "      api_level:\n        type: string\n"
        "      include_api24_smoke:\n        type: boolean\n"
        "      artifact_prefix:\n        type: string\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/upload-artifact@v4\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ANDROID_WF", own)
    saved = run_hosted_workflow_runner_audit_drill(ops_dir=real)
    saved_text = (real / kept.name).read_text(encoding="utf-8")
    assert saved["android"]["checks"]["present"] is True
    assert saved["android"]["required_inputs"]["api_level"] is True
    assert saved["android"]["checks"]["upload_artifact"] is True
    assert saved["android"]["ok"] is True
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert saved["live_hosted_runners"] is False
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_runner_audit_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-runner-audit-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-runner-audit-link")
    assert row["status"] == "done"
    gates = {gate["id"]: gate["status"] for gate in snap["gates"]}
    assert gates["D"] != "done"
    assert gates["F"] != "done"
    assert snap["complete"] is False
