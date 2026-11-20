"""Flaky/auth/infra healing policy stays incomplete for Gate E."""
from backend.production_healing_flaky_policy_drill import (
    run_production_healing_flaky_policy_drill,
)


def test_production_healing_flaky_policy_stays_partial(tmp_path):
    evidence = run_production_healing_flaky_policy_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["ok"] is True
    assert evidence["policy"]["flaky_auth_infra_auto_apply"] is False
    assert evidence["policy"]["assertion_weaken_denied"] is True
    assert (tmp_path / "production_healing_flaky_policy_drill.json").is_file()
