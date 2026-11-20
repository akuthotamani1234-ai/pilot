"""Dual-region store health probe stays incomplete for Gate H."""
from backend.dual_region_store_health_probe_drill import (
    run_dual_region_store_health_probe_drill,
)


def test_dual_region_store_health_probe_stays_partial(tmp_path, monkeypatch):
    import backend.dual_region_store_health_probe_drill as mod

    monkeypatch.setattr(mod, "_tcp_ok", lambda host, port, timeout=1.5: True)
    evidence = run_dual_region_store_health_probe_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["live_hosted_dr"] is False
    assert evidence["ok"] is True
    assert evidence["primary_up"] == 3
    assert (tmp_path / "dual_region_store_health_probe_drill.json").is_file()
