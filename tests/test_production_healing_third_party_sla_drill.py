"""Third-party healing SLA stays incomplete for Gate E."""
from backend.production_healing_third_party_sla_drill import (
    run_production_healing_third_party_sla_drill,
)


def test_production_healing_third_party_sla_stays_partial(tmp_path, monkeypatch):
    import backend.production_healing_third_party_sla_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in mod.LOCAL_PARTIAL:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_production_healing_third_party_sla_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["production_suite_executed"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "production_healing_third_party_sla_drill.json").is_file()
