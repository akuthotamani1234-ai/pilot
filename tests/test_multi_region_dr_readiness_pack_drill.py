"""Multi-region DR readiness pack stays incomplete for Gate H."""
from backend.multi_region_dr_readiness_pack_drill import (
    run_multi_region_dr_readiness_pack_drill,
)


def test_multi_region_dr_readiness_pack_stays_partial(tmp_path, monkeypatch):
    # Stub children so offline CI (no Postgres/psql) still exercises the pack.
    import backend.failover_rto_drill as failover
    import backend.hosted_oncall_readiness_pack_drill as oncall
    import backend.multi_region_cutover_rehearsal_drill as cutover
    import backend.multi_store_dr_drill as multi

    monkeypatch.setattr(
        multi, "run_multi_store_dr_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        failover, "run_failover_rto_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        cutover, "run_multi_region_cutover_rehearsal_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        oncall, "run_hosted_oncall_readiness_pack_drill",
        lambda ops_dir=None: {"ok": True},
    )
    evidence = run_multi_region_dr_readiness_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["live_hosted_dr"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "multi_region_dr_readiness_pack_drill.json").is_file()
