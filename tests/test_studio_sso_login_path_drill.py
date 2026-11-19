"""Studio SSO login-path stays incomplete for Gate I."""
from backend.studio_sso_login_path_drill import STEPS, run_studio_sso_login_path_drill


def test_studio_sso_login_path_stays_partial(tmp_path, monkeypatch):
    import backend.studio_sso_login_path_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for _, artifact, _ in STEPS:
        (ops / artifact).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_studio_sso_login_path_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["score_of"] == len(STEPS)
    assert (tmp_path / "studio_sso_login_path_drill.json").is_file()
