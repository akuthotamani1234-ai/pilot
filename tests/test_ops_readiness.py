"""Gate H: ops readiness never claims complete from docs alone."""
from backend.ops_readiness import readiness


def test_ops_readiness_lists_gaps_and_stays_incomplete():
    snap = readiness()
    assert snap["gate_h_complete"] is False
    # Local drill evidence under artifacts/ops may be present after a drill POST;
    # load/incident remain open either way.
    assert "ci_workflow" in snap["checks"]
    assert snap["checks"]["ops_drill_checklist"]["ready"] is True
    assert "ops_drill_checklist" in snap["ready"]
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]

    def has(name: str) -> bool:
        return (
            (root / "artifacts" / "ops" / name).is_file()
            or (root / "docs" / "ops-evidence" / name).is_file()
        )

    assert snap["checks"]["backup_restore_drill"]["ready"] is has("backup_restore_drill.json")
    assert snap["checks"]["load_test"]["ready"] is has("local_load_probe.json")
    assert snap["checks"]["controlled_soak"]["ready"] is has("controlled_soak_drill.json")
    if has("local_load_probe.json"):
        assert "load_test" in snap["ready"]
    else:
        assert "load_test" in snap["missing"]
    if has("controlled_soak_drill.json"):
        assert "controlled_soak" in snap["ready"]
    else:
        assert "controlled_soak" in snap["missing"]
    assert snap["checks"]["failure_matrix_drill"]["ready"] is has("failure_matrix_drill.json")
    assert snap["checks"]["healing_regression_drill"]["ready"] is has("healing_regression_drill.json")
    assert snap["checks"]["api_version_contract"]["ready"] is has("api_version_contract.json")
    assert snap["checks"]["pg_tenancy_drill"]["ready"] is has("pg_tenancy_drill.json")
    assert snap["checks"]["visual_portfolio_drill"]["ready"] is has("visual_portfolio_drill.json")
    assert snap["checks"]["perf_portfolio_drill"]["ready"] is has("perf_portfolio_drill.json")
    assert snap["checks"]["compatibility_portfolio_drill"]["ready"] is has(
        "compatibility_portfolio_drill.json"
    )
    assert snap["checks"]["admin_portal_lifecycle_drill"]["ready"] is has(
        "admin_portal_lifecycle_drill.json"
    )
    assert snap["checks"]["oracle_spec_drill"]["ready"] is has("oracle_spec_drill.json")
    assert snap["checks"]["swarm_retry_drill"]["ready"] is has("swarm_retry_drill.json")
    assert snap["checks"]["demo_store_cart_lifecycle_drill"]["ready"] is has(
        "demo_store_cart_lifecycle_drill.json"
    )
    assert snap["checks"]["audit_export_drill"]["ready"] is has("audit_export_drill.json")
    assert snap["checks"]["dashboard_auth_matrix_drill"]["ready"] is has(
        "dashboard_auth_matrix_drill.json"
    )
