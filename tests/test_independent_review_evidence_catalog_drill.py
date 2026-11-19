"""Independent review evidence catalog stays unsigned for Gate G."""
from backend.independent_review_evidence_catalog_drill import (
    run_independent_review_evidence_catalog_drill,
)


def test_independent_review_evidence_catalog_stays_partial(tmp_path):
    # Seed a few evidence files so the catalog has content offline.
    for name in (
        "remaining_blockers.json",
        "independent_review_pack.json",
        "loopback_sso_drill.json",
        "multi_region_dr_drill.json",
        "android_appium_product_matrix_drill.json",
        "multi_browser_portfolio_suite_drill.json",
        "production_healing_matrix_drill.json",
        "failover_rto_drill.json",
        "hosted_idp_readiness_drill.json",
        "hosted_oncall_readiness_drill.json",
        "ci_artifact_upload_rehearsal_drill.json",
        "workflow_dispatch_contract_drill.json",
        "healing_regression_drill.json",
        "paging_ack_drill.json",
        "oidc_tid_tenant_acl_drill.json",
        "multi_store_dr_drill.json",
        "device_artifact_manifest_drill.json",
        "portfolio_artifact_manifest_drill.json",
        "production_healing_flaky_policy_drill.json",
        "independent_review_integrity_drill.json",
        "INDEPENDENT_REVIEW_SUMMARY.md",
    ):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    evidence = run_independent_review_evidence_catalog_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert evidence["entry_count"] >= 20
    assert (tmp_path / "independent_review_evidence_catalog_drill.json").is_file()
