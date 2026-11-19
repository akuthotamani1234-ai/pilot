"""A cache-key contract reads this install's workflow. A link is left unread."""
from backend.blueprint_progress import progress
from backend.hosted_ci_cache_key_contract_drill import (
    LOCAL_PARTIAL,
    run_hosted_ci_cache_key_contract_drill,
)


def test_a_cache_key_contract_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.hosted_ci_cache_key_contract_drill as mod

    secret = "tenant-b-only-cache-key"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "hosted_ci_cache_key_contract_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_hosted_ci_cache_key_contract_drill(ops_dir=linked)
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
        f"{secret}\nactions/cache\n  workflow_dispatch:\n",
        encoding="utf-8",
    )
    android_link = tmp_path / "android-link.yml"
    android_link.symlink_to(secret_yaml)
    browsers = tmp_path / "browsers.yml"
    browsers.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")
    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    leaked_name = LOCAL_PARTIAL[0]
    (ops / leaked_name).symlink_to(kept)
    for name in LOCAL_PARTIAL[1:]:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ANDROID_WF", android_link)
    monkeypatch.setattr(mod, "BROWSER_WF", browsers)
    real = tmp_path / "real"
    real.mkdir()
    skipped = run_hosted_ci_cache_key_contract_drill(ops_dir=real)
    written = (real / kept.name).read_text(encoding="utf-8")
    android = skipped["contract"]["android"]["workflow"]
    assert android["present"] is False
    assert android["actions_cache_mentioned"] is False
    assert leaked_name not in skipped["local_partial_present"]
    assert secret not in written
    assert kept.read_bytes() == original

    own = tmp_path / "own-android.yml"
    token = "this-install-cache-key"
    own.write_text(f"{token}\nactions/cache\n  workflow_dispatch:\n", encoding="utf-8")
    (ops / leaked_name).unlink()
    (ops / leaked_name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ANDROID_WF", own)
    saved = run_hosted_ci_cache_key_contract_drill(ops_dir=real)
    saved_text = (real / kept.name).read_text(encoding="utf-8")
    own_workflow = saved["contract"]["android"]["workflow"]
    assert own_workflow["present"] is True
    assert own_workflow["actions_cache_mentioned"] is True
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert saved["live_hosted_runners"] is False
    assert leaked_name in saved["local_partial_present"]
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_cache_key_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-cache-key-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-cache-key-link")
    assert row["status"] == "done"
    gates = {gate["id"]: gate["status"] for gate in snap["gates"]}
    assert gates["D"] != "done"
    assert gates["F"] != "done"
    assert snap["complete"] is False
