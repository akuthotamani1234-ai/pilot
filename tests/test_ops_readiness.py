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
    assert snap["checks"]["approvals_drill"]["ready"] is has("approvals_drill.json")
    assert snap["checks"]["sso_contract_drill"]["ready"] is has("sso_contract_drill.json")
    assert snap["checks"]["incident_tabletop_drill"]["ready"] is (
        has("incident_tabletop_drill.json") or has("incident_tabletop_stub.json")
    )
    assert snap["checks"]["android_emulator_smoke_drill"]["ready"] is has(
        "android_emulator_smoke_drill.json"
    )
    assert snap["checks"]["android_appium_product_matrix_drill"]["ready"] is has(
        "android_appium_product_matrix_drill.json"
    )
    assert snap["checks"]["android_appium_ci_contract"]["ready"] is has(
        "android_appium_ci_contract.json"
    )
    assert snap["checks"]["discovery_score_drill"]["ready"] is has("discovery_score_drill.json")
    assert snap["checks"]["multi_browser_portfolio_suite_drill"]["ready"] is has(
        "multi_browser_portfolio_suite_drill.json"
    )
    assert snap["checks"]["multi_browser_ci_contract"]["ready"] is has(
        "multi_browser_ci_contract.json"
    )
    assert snap["checks"]["multi_device_ci_contract"]["ready"] is has(
        "multi_device_ci_contract.json"
    )
    assert snap["checks"]["loopback_sso_drill"]["ready"] is has("loopback_sso_drill.json")
    assert snap["checks"]["loopback_auth_code_sso_drill"]["ready"] is has(
        "loopback_auth_code_sso_drill.json"
    )
    assert snap["checks"]["demo_store_healing_live_drill"]["ready"] is has(
        "demo_store_healing_live_drill.json"
    )
    assert snap["checks"]["postgres_dr_drill"]["ready"] is has("postgres_dr_drill.json")
    assert snap["checks"]["multi_region_dr_drill"]["ready"] is has("multi_region_dr_drill.json")
    assert snap["checks"]["minio_multi_region_drill"]["ready"] is has(
        "minio_multi_region_drill.json"
    )
    assert snap["checks"]["redis_multi_region_drill"]["ready"] is has(
        "redis_multi_region_drill.json"
    )
    assert snap["checks"]["observability_probe_drill"]["ready"] is has(
        "observability_probe_drill.json"
    )
    assert snap["checks"]["paging_escalation_drill"]["ready"] is has(
        "paging_escalation_drill.json"
    )
    assert snap["checks"]["live_failure_matrix_drill"]["ready"] is has(
        "live_failure_matrix_drill.json"
    )
    assert snap["checks"]["multi_app_healing_suite_drill"]["ready"] is has(
        "multi_app_healing_suite_drill.json"
    )
    assert snap["checks"]["sso_tenant_acl_drill"]["ready"] is has("sso_tenant_acl_drill.json")
    assert snap["checks"]["independent_review_checklist"]["ready"] is True
    assert snap["checks"]["independent_review_pack"]["ready"] is has(
        "independent_review_pack.json"
    )
    assert snap["checks"]["mutation_score_drill"]["ready"] is has("mutation_score_drill.json")
    assert snap["checks"]["cross_platform_journey_drill"]["ready"] is has(
        "cross_platform_journey_drill.json"
    )
    assert snap["checks"]["multi_api_android_matrix_drill"]["ready"] is has(
        "multi_api_android_matrix_drill.json"
    )
    assert snap["checks"]["qx_capabilities_drill"]["ready"] is has("qx_capabilities_drill.json")
    assert snap["checks"]["qx_core_capabilities_drill"]["ready"] is has(
        "qx_core_capabilities_drill.json"
    )
