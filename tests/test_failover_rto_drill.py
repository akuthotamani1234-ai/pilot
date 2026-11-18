from pathlib import Path

from backend.failover_rto_drill import run_failover_rto_drill


def test_failover_rto_reports_honestly(tmp_path: Path):
    evidence = run_failover_rto_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert (tmp_path / "failover_rto_drill.json").is_file()
    assert evidence.get("total") == 3
    assert "local_rto_budget_ms" in evidence
    # ok depends on live PG/MinIO/Redis; always honest about gate
    assert isinstance(evidence.get("ok"), bool)
