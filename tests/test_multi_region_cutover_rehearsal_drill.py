"""Multi-region cutover rehearsal stays incomplete for Gate H."""
from backend.multi_region_cutover_rehearsal_drill import (
    run_multi_region_cutover_rehearsal_drill,
)


def test_multi_region_cutover_rehearsal_stays_partial(tmp_path, monkeypatch):
    # Offline unit path: clear store URLs so missing binaries/services do not
    # crash; the pack must still refuse gate completion.
    for key in (
        "POSTGRES_URL", "QPILOT_DB_URL", "DATABASE_URL",
        "REDIS_URL", "QPILOT_REDIS_URL",
        "OBJECT_STORE_URI", "MINIO_URL", "MINIO_ENDPOINT",
        "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    evidence = run_multi_region_cutover_rehearsal_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["steps_total"] == 5
    assert isinstance(evidence.get("steps_passed"), int)
    assert (tmp_path / "multi_region_cutover_rehearsal_drill.json").is_file()
