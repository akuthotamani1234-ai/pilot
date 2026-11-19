"""Production healing seed catalog stays incomplete for Gate E."""
from backend.production_healing_seed_catalog_drill import (
    SEEDS,
    run_production_healing_seed_catalog_drill,
)


def test_production_healing_seed_catalog_stays_partial(tmp_path, monkeypatch):
    import backend.production_healing_seed_catalog_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for _, artifact, _ in SEEDS:
        (ops / artifact).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_production_healing_seed_catalog_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["production_suite_executed"] is False
    assert evidence["ok"] is True
    assert evidence["score_of"] == len(SEEDS)
    assert (tmp_path / "production_healing_seed_catalog_drill.json").is_file()
