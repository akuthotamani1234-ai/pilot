"""Studio SSO session rebind stays incomplete for Gate I."""
from backend.studio_sso_session_rebind_drill import run_studio_sso_session_rebind_drill


def test_studio_sso_session_rebind_stays_partial(tmp_path):
    evidence = run_studio_sso_session_rebind_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["tokens_distinct"] is True
    assert (tmp_path / "studio_sso_session_rebind_drill.json").is_file()
