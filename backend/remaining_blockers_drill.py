"""Blueprint honesty: inventory hard-open blockers for Studio sidebar.

Does not close any gate. Records what still needs hosted / independent
evidence before A–J can leave Partial.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "remaining_blockers.json"

BLOCKERS = (
    {
        "id": "H-drills",
        "gate": "H",
        "label": "Live hosted multi-region DR / on-call paging",
        "local_partial": [
            "multi_region_dr_drill.json",
            "minio_multi_region_drill.json",
            "redis_multi_region_drill.json",
            "multi_store_dr_drill.json",
            "failover_rto_drill.json",
            "multi_region_cutover_rehearsal_drill.json",
            "paging_escalation_drill.json",
            "paging_ack_drill.json",
            "paging_escalation_ack_pack_drill.json",
            "hosted_oncall_contract_drill.json",
            "hosted_oncall_readiness_drill.json",
            "hosted_oncall_readiness_pack_drill.json",
            "multi_region_dr_readiness_pack_drill.json",
            "dual_region_store_health_probe_drill.json",
            "hosted_dr_cutover_checklist_drill.json",
            "hosted_oncall_rota_contract_drill.json",
            "hosted_dr_rpo_contract_drill.json",
            "hosted_dr_comms_contract_drill.json",
            "paging_severity_routing_contract_drill.json",
            "dual_region_replication_lag_contract_drill.json",
        ],
    },
    {
        "id": "I-auth",
        "gate": "I",
        "label": "Live hosted IdP Studio SSO login + multi-tenant ACLs",
        "local_partial": [
            "loopback_sso_drill.json",
            "loopback_auth_code_sso_drill.json",
            "loopback_pkce_sso_drill.json",
            "studio_oidc_callback_drill.json",
            "sso_tenant_acl_drill.json",
            "dual_tenant_oidc_acl_drill.json",
            "oidc_groups_role_acl_drill.json",
            "oidc_tid_tenant_acl_drill.json",
            "oidc_email_domain_tenant_acl_drill.json",
            "studio_sso_principal_bootstrap_drill.json",
            "hosted_idp_contract_drill.json",
            "hosted_idp_readiness_drill.json",
            "hosted_idp_sso_readiness_pack_drill.json",
            "oidc_org_tenant_acl_drill.json",
            "oidc_acl_matrix_pack_drill.json",
            "hosted_idp_claim_map_completeness_drill.json",
            "studio_sso_login_path_drill.json",
            "studio_sso_session_rebind_drill.json",
            "studio_sso_audience_binding_drill.json",
            "studio_sso_token_expiry_drill.json",
            "studio_sso_state_binding_drill.json",
            "studio_sso_nonce_binding_drill.json",
            "studio_sso_jti_replay_drill.json",
            "studio_sso_nbf_drill.json",
            "hosted_idp_metadata_contract_drill.json",
            "hosted_idp_redirect_uri_allowlist_drill.json",
            "studio_sso_redirect_allowlist_enforcement_drill.json",
            "studio_sso_code_reuse_drill.json",
        ],
    },
    {
        "id": "E-live-matrix",
        "gate": "E",
        "label": "Production failure matrix / healing suite",
        "local_partial": [
            "live_failure_matrix_drill.json",
            "multi_app_healing_suite_drill.json",
            "production_healing_matrix_drill.json",
            "production_healing_taxonomy_drill.json",
            "production_healing_contract_drill.json",
            "production_healing_replay_pack_drill.json",
            "production_healing_flaky_policy_drill.json",
            "production_healing_readiness_drill.json",
            "production_healing_suite_pack_drill.json",
            "production_healing_third_party_sla_drill.json",
            "production_healing_acceptance_gate_drill.json",
            "production_healing_seed_catalog_drill.json",
            "production_healing_fixture_coverage_drill.json",
            "production_healing_rollback_policy_drill.json",
            "production_healing_human_loop_contract_drill.json",
            "production_healing_budget_contract_drill.json",
            "production_healing_escalation_ladder_drill.json",
            "healing_regression_drill.json",
        ],
    },
    {
        "id": "D-android",
        "gate": "D",
        "label": "Broad multi-device CI Appium product-matrix artifacts",
        "local_partial": [
            "android_appium_product_matrix_drill.json",
            "android_emulator_smoke_api24_drill.json",
            "multi_api_android_matrix_drill.json",
            "multi_device_ci_contract.json",
            "device_artifact_manifest_drill.json",
            "apidemos_interaction_drill.json",
            "workflow_dispatch_contract_drill.json",
            "hosted_ci_runner_matrix_drill.json",
            "ci_artifact_upload_rehearsal_drill.json",
            "hosted_runner_readiness_drill.json",
            "hosted_dispatch_payload_rehearsal_drill.json",
            "hosted_ci_artifact_gate_pack_drill.json",
            "android_device_ci_readiness_pack_drill.json",
            "hosted_workflow_runner_audit_drill.json",
            "hosted_ci_artifact_retention_contract_drill.json",
            "hosted_ci_permissions_contract_drill.json",
            "hosted_ci_timeout_budget_drill.json",
            "hosted_ci_concurrency_contract_drill.json",
            "hosted_runner_os_matrix_contract_drill.json",
            "hosted_ci_cache_key_contract_drill.json",
        ],
    },
    {
        "id": "F-live-ci",
        "gate": "F",
        "label": "Broad hosted multi-browser portfolio CI artifacts",
        "local_partial": [
            "multi_browser_portfolio_suite_drill.json",
            "multi_browser_ci_contract.json",
            "portfolio_artifact_manifest_drill.json",
            "workflow_dispatch_contract_drill.json",
            "hosted_ci_runner_matrix_drill.json",
            "ci_artifact_upload_rehearsal_drill.json",
            "hosted_runner_readiness_drill.json",
            "hosted_dispatch_payload_rehearsal_drill.json",
            "hosted_ci_artifact_gate_pack_drill.json",
            "browser_portfolio_ci_readiness_pack_drill.json",
            "hosted_workflow_runner_audit_drill.json",
            "hosted_ci_artifact_retention_contract_drill.json",
            "hosted_ci_permissions_contract_drill.json",
            "hosted_ci_timeout_budget_drill.json",
            "hosted_ci_concurrency_contract_drill.json",
            "hosted_runner_os_matrix_contract_drill.json",
            "hosted_ci_cache_key_contract_drill.json",
        ],
    },
    {
        "id": "G-review",
        "gate": "G",
        "label": "Independent security/reliability review sign-off",
        "local_partial": [
            "independent_review_checklist.json",
            "independent_review_pack.json",
            "independent_review_readiness_drill.json",
            "independent_review_summary_drill.json",
            "independent_review_request_drill.json",
            "independent_review_integrity_drill.json",
            "independent_review_evidence_catalog_drill.json",
            "independent_review_attestation_drill.json",
            "independent_review_signoff_pack_drill.json",
            "independent_review_handoff_pack_drill.json",
            "independent_review_findings_template_drill.json",
            "independent_review_scope_matrix_drill.json",
            "independent_review_blocker_freeze_drill.json",
            "independent_review_response_sla_drill.json",
            "independent_reviewer_roster_contract_drill.json",
            "independent_review_findings_freeze_drill.json",
            "independent_review_window_contract_drill.json",
            "independent_review_evidence_retention_contract_drill.json",
            "INDEPENDENT_REVIEW_SUMMARY.md",
            "INDEPENDENT_REVIEW_ATTESTATION.md",
            "INDEPENDENT_REVIEW_FINDINGS.md",
        ],
    },
)


def run_remaining_blockers_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for blocker in BLOCKERS:
        present = [
            name for name in blocker["local_partial"]
            if (ops / name).is_file()
        ]
        rows.append({
            **blocker,
            "status": "open",
            "local_partial_present": present,
            "local_partial_missing": [
                name for name in blocker["local_partial"] if name not in present
            ],
        })
    evidence = {
        "complete": False,
        "drill": "remaining_blockers",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ok": True,
        "blockers": rows,
        "open_count": len(rows),
        "reason": (
            f"{len(rows)} hard-open blockers remain (hosted DR/SSO, production healing, "
            "broad CI runners, independent sign-off); gates A–J stay Partial"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "remaining_blockers.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "remaining_blockers.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
