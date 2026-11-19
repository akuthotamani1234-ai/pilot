"""Multi-region cutover rehearsal stays incomplete for Gate H."""
from backend.multi_region_cutover_rehearsal_drill import (
    run_multi_region_cutover_rehearsal_drill,
)


def test_multi_region_cutover_rehearsal_stays_partial(tmp_path, monkeypatch):
    # Offline unit path: mark store drills as unavailable without live services
    # by ensuring the pack still refuses gate completion.
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("QPILOT_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    evidence = run_multi_region_cutover_rehearsal_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["steps_total"] == 5
    assert (tmp_path / "multi_region_cutover_rehearsal_drill.json").is_file()
