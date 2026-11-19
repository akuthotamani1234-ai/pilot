"""Production healing readiness stays incomplete for Gate E."""
from backend.production_healing_readiness_drill import (
    run_production_healing_readiness_drill,
)


def test_production_healing_readiness_stays_partial(tmp_path, monkeypatch):
    import backend.production_healing_readiness_drill as mod

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name, _ in mod.CHECKS:
        (ops / name).write_text("{}", encoding="utf-8")
    evidence = run_production_healing_readiness_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["production_suite_executed"] is False
    assert evidence["ok"] is True
    assert evidence["score"] == evidence["score_of"]
    assert (tmp_path / "production_healing_readiness_drill.json").is_file()
