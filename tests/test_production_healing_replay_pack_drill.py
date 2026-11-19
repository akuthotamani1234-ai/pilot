"""Production healing replay pack stays incomplete for Gate E."""
from backend.production_healing_replay_pack_drill import (
    run_production_healing_replay_pack_drill,
)


def test_production_healing_replay_pack_stays_partial(tmp_path):
    evidence = run_production_healing_replay_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence["ok"] is True
    assert evidence["passed"] == 4
    assert evidence["pack_sha256"]
    assert (tmp_path / "production_healing_replay_pack_drill.json").is_file()
