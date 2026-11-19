"""Studio SSO audience binding stays incomplete for Gate I."""
from backend.studio_sso_audience_binding_drill import (
    run_studio_sso_audience_binding_drill,
)


def test_studio_sso_audience_binding_stays_partial(tmp_path):
    evidence = run_studio_sso_audience_binding_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["good_ok"] is True
    assert evidence["bad_rejected"] is True
    assert (tmp_path / "studio_sso_audience_binding_drill.json").is_file()
