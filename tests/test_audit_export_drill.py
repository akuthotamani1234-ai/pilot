"""Gate G audit export drill stays incomplete and isolates tenants."""
from pathlib import Path

from backend.audit_export_drill import run_audit_export_drill


def test_audit_export_drill_scopes_tenants(tmp_path: Path):
    evidence = run_audit_export_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["ok"] is True
    assert evidence["scoped_count"] == 2
    assert evidence["scoped_tenants"] == ["t-a"]
    assert evidence["other_count"] == 1
    assert evidence["unknown_count"] == 0
    assert evidence["unscoped_count"] >= 3
    assert (tmp_path / "audit_export_drill.json").is_file()
