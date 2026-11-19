"""Hosted workflow runner audit stays incomplete for Gates D/F."""
from backend.hosted_workflow_runner_audit_drill import (
    run_hosted_workflow_runner_audit_drill,
)


def test_hosted_workflow_runner_audit_stays_partial(tmp_path, monkeypatch):
    import backend.hosted_workflow_runner_audit_drill as mod

    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    android = wf / "android-appium.yml"
    browser = wf / "multi-browser-portfolios.yml"
    android.write_text(
        "on:\n  workflow_dispatch:\n    inputs:\n"
        "      api_level:\n        type: string\n"
        "      include_api24_smoke:\n        type: boolean\n"
        "      artifact_prefix:\n        type: string\n"
        "permissions:\n  contents: read\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/upload-artifact@v4\n"
        "        # Hosted runners still open / KVM\n",
        encoding="utf-8",
    )
    browser.write_text(
        "on:\n  workflow_dispatch:\n    inputs:\n"
        "      engines:\n        type: string\n"
        "      portfolio:\n        type: string\n"
        "      artifact_prefix:\n        type: string\n"
        "permissions:\n  contents: read\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/upload-artifact@v4\n"
        "        # Hosted multi-browser still open\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ANDROID_WF", android)
    monkeypatch.setattr(mod, "BROWSER_WF", browser)
    evidence = run_hosted_workflow_runner_audit_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["live_hosted_runners"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "hosted_workflow_runner_audit_drill.json").is_file()
