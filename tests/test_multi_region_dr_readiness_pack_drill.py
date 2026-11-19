"""Multi-region DR readiness pack stays incomplete for Gate H."""
from backend.multi_region_dr_readiness_pack_drill import (
    run_multi_region_dr_readiness_pack_drill,
)


def test_multi_region_dr_readiness_pack_stays_partial(tmp_path):
    evidence = run_multi_region_dr_readiness_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["live_hosted_dr"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "multi_region_dr_readiness_pack_drill.json").is_file()
