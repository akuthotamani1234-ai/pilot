"""Production healing suite pack stays incomplete for Gate E."""
from backend.production_healing_suite_pack_drill import (
    run_production_healing_suite_pack_drill,
)


def test_production_healing_suite_pack_stays_partial(tmp_path, monkeypatch):
    import backend.multi_app_healing_suite_drill as multi
    import backend.production_healing_flaky_policy_drill as flaky
    import backend.production_healing_readiness_drill as ready
    import backend.production_healing_replay_pack_drill as replay
    import backend.production_healing_taxonomy_drill as tax

    monkeypatch.setattr(
        ready, "run_production_healing_readiness_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        flaky, "run_production_healing_flaky_policy_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        replay, "run_production_healing_replay_pack_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        tax, "run_production_healing_taxonomy_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        multi, "run_multi_app_healing_suite_drill",
        lambda ops_dir=None: {"ok": True},
    )
    evidence = run_production_healing_suite_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["production_suite_executed"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "production_healing_suite_pack_drill.json").is_file()
