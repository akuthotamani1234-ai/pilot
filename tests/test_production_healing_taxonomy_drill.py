from pathlib import Path

from backend.production_healing_taxonomy_drill import (
    run_production_healing_taxonomy_drill,
)


def test_production_healing_taxonomy_reports_honestly(tmp_path: Path):
    evidence = run_production_healing_taxonomy_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert (tmp_path / "production_healing_taxonomy_drill.json").is_file()
    assert evidence.get("matched") == evidence.get("total") == 6
    assert evidence["healing"]["locator_repair_allowed"] is True
    assert evidence["healing"]["weaken_denied"] is True
