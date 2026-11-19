"""Production healing budget contract stays incomplete for Gate E."""
from backend.production_healing_budget_contract_drill import (
    LOCAL_PARTIAL,
    run_production_healing_budget_contract_drill,
)


def test_production_healing_budget_contract_stays_partial(tmp_path, monkeypatch):
    import backend.production_healing_budget_contract_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in LOCAL_PARTIAL:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_production_healing_budget_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["production_suite_executed"] is False
    assert evidence["ok"] is True
    assert evidence["budget"]["max_wall_minutes"] == 90
    assert (tmp_path / "production_healing_budget_contract_drill.json").is_file()
