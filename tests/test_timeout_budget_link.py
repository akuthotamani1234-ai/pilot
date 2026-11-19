"""A timeout budget records this install's minutes. A link is left unread."""
from backend.blueprint_progress import progress
from backend.hosted_ci_timeout_budget_drill import run_hosted_ci_timeout_budget_drill


def test_a_timeout_budget_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.hosted_ci_timeout_budget_drill as mod

    calls = {"n": 0}
    real_budget = mod._budget

    def _budget(*args, **kwargs):
        calls["n"] += 1
        return real_budget(*args, **kwargs)

    monkeypatch.setattr(mod, "_budget", _budget)

    secret = "tenant-b-only-timeout"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "hosted_ci_timeout_budget_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_hosted_ci_timeout_budget_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert refused["gate_f_complete"] is False
    assert refused["live_hosted_runners"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    folder = tmp_path / "planted"
    folder.mkdir()
    planted = folder / kept.name
    planted.symlink_to(kept)
    skipped_file = run_hosted_ci_timeout_budget_drill(ops_dir=folder)
    assert "link" in skipped_file["reason"]
    assert skipped_file["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped_file)
    assert kept.read_bytes() == original
    assert planted.is_symlink()

    secret_yaml = other / "secret-workflow.yml"
    secret_yaml.write_text(f"# {secret}\ntimeout-minutes: 777\n", encoding="utf-8")
    android_link = tmp_path / "android-link.yml"
    android_link.symlink_to(secret_yaml)
    monkeypatch.setattr(mod, "ANDROID_WF", android_link)
    real = tmp_path / "real"
    real.mkdir()
    skipped = run_hosted_ci_timeout_budget_drill(ops_dir=real)
    written = (real / kept.name).read_text(encoding="utf-8")
    assert calls["n"] == 2
    assert skipped["android"]["timeout_minutes"] is None
    assert skipped["android"]["ok"] is False
    assert "777" not in written
    assert secret not in written
    assert kept.read_bytes() == original

    own = tmp_path / "own-android.yml"
    own.write_text("timeout-minutes: 60\n", encoding="utf-8")
    monkeypatch.setattr(mod, "ANDROID_WF", own)
    saved = run_hosted_ci_timeout_budget_drill(ops_dir=real)
    saved_text = (real / kept.name).read_text(encoding="utf-8")
    assert calls["n"] == 4
    assert saved["android"]["timeout_minutes"] == 60
    assert saved["android"]["ok"] is True
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert saved["live_hosted_runners"] is False
    assert "777" not in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_timeout_budget_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-timeout-budget-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-timeout-budget-link")
    assert row["status"] == "done"
    gates = {gate["id"]: gate["status"] for gate in snap["gates"]}
    assert gates["D"] != "done"
    assert gates["F"] != "done"
    assert snap["complete"] is False
