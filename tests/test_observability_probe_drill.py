from pathlib import Path

from backend.observability_probe_drill import run_observability_probe_drill


def test_observability_probe_stays_incomplete(tmp_path: Path):
    evidence = run_observability_probe_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence.get("ops_readiness_complete") is False
    assert evidence.get("ok") is True
    assert evidence.get("checks_total", 0) > 0
    assert (tmp_path / "observability_probe_drill.json").is_file()
