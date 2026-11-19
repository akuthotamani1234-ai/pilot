"""Hosted CI cache-key contract stays incomplete for Gates D/F."""
from backend.hosted_ci_cache_key_contract_drill import (
    LOCAL_PARTIAL,
    run_hosted_ci_cache_key_contract_drill,
)


def test_hosted_ci_cache_key_contract_stays_partial(tmp_path, monkeypatch):
    import backend.hosted_ci_cache_key_contract_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in LOCAL_PARTIAL:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    # Point workflow paths at missing files under tmp — ok uses present local
    # partials + workflow presence; stub workflows so present=True.
    android = tmp_path / ".github" / "workflows" / "android-appium.yml"
    browsers = tmp_path / ".github" / "workflows" / "multi-browser-portfolios.yml"
    android.parent.mkdir(parents=True)
    android.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")
    browsers.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")
    monkeypatch.setattr(mod, "ANDROID_WF", android)
    monkeypatch.setattr(mod, "BROWSER_WF", browsers)
    evidence = run_hosted_ci_cache_key_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["live_hosted_runners"] is False
    assert evidence["ok"] is True
    assert evidence["contract"]["android"]["keys"]
    assert (tmp_path / "hosted_ci_cache_key_contract_drill.json").is_file()
