"""Gate H operations readiness probe.

Reports which ops artifacts exist locally without claiming hardened production
ops, load tests, or DR drills are complete.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _ops_evidence(*names: str) -> bool:
    """True if any named evidence file exists under artifacts/ops or docs/ops-evidence."""
    for name in names:
        if (ROOT / "artifacts" / "ops" / name).is_file():
            return True
        if (ROOT / "docs" / "ops-evidence" / name).is_file():
            return True
    return False


def _file_check(rel: str, *, ready_reason: str, missing_reason: str) -> dict:
    path = ROOT / rel
    ok = path.is_file()
    return {
        "ready": ok,
        "path": rel,
        "reason": ready_reason if ok else missing_reason,
    }


def readiness() -> dict:
    """Snapshot of Gate H foundations. Never sets gate_h_complete True here."""
    checks = {
        "ci_workflow": (
            _file_check(
                ".github/workflows/qpilot.yml",
                ready_reason="CI workflow qpilot.yml is present",
                missing_reason="No qpilot.yml GitHub Actions workflow found",
            )
            if (ROOT / ".github" / "workflows" / "qpilot.yml").is_file()
            else _file_check(
                ".github/workflows/ci.yml",
                ready_reason="CI workflow ci.yml is present",
                missing_reason="No CI workflow found under .github/workflows/",
            )
        ),
        "deployment_doc": _file_check(
            "DEPLOYMENT.md",
            ready_reason="DEPLOYMENT.md documents operator deploy steps",
            missing_reason="DEPLOYMENT.md missing",
        ),
        "security_doc": _file_check(
            "SECURITY.md",
            ready_reason="SECURITY.md present for reporting path",
            missing_reason="SECURITY.md missing",
        ),
        "observability": {
            "ready": _ops_evidence("local_metrics_snapshot.json"),
            "reason": (
                "Local metrics snapshot present; central metrics/tracing/alerting still open"
                if _ops_evidence("local_metrics_snapshot.json")
                else "Central metrics/tracing/alerting stack not established in-repo"
            ),
        },
        "backup_restore_drill": {
            "ready": _ops_evidence("backup_restore_drill.json"),
            "reason": (
                "Local SQLite backup/restore evidence present; live DR/object-store drills still open"
                if _ops_evidence("backup_restore_drill.json")
                else "No recorded backup/restore drill evidence"
            ),
        },
        "object_store_backup_restore": {
            "ready": _ops_evidence("minio_backup_restore_drill.json"),
            "reason": (
                "Live MinIO object backup/restore evidence present; hosted DR still open"
                if _ops_evidence("minio_backup_restore_drill.json")
                else "No MinIO object-store backup/restore evidence"
            ),
        },
        "postgres_dr_drill": {
            "ready": _ops_evidence("postgres_dr_drill.json"),
            "reason": (
                "Postgres dump→isolated-DB restore evidence present; hosted multi-region DR still open"
                if _ops_evidence("postgres_dr_drill.json")
                else "No Postgres DR drill evidence"
            ),
        },
        "admin_portal_surfaces": {
            "ready": _ops_evidence("admin_portal_surface_coverage.json"),
            "reason": (
                "AdminPortal surface_coverage inventory present; full Gate A live matrix still open"
                if _ops_evidence("admin_portal_surface_coverage.json")
                else "No AdminPortal surface coverage inventory"
            ),
        },
        "demo_store_surfaces": {
            "ready": _ops_evidence("demo_store_surface_coverage.json"),
            "reason": (
                "DemoStore surface_coverage inventory present; full Gate A live matrix still open"
                if _ops_evidence("demo_store_surface_coverage.json")
                else "No DemoStore surface coverage inventory"
            ),
        },
        "classic_shop_surfaces": {
            "ready": _ops_evidence("classic_shop_surface_coverage.json"),
            "reason": (
                "ClassicShop surface_coverage inventory present; full Gate A live matrix still open"
                if _ops_evidence("classic_shop_surface_coverage.json")
                else "No ClassicShop surface coverage inventory"
            ),
        },
        "travel_site_surfaces": {
            "ready": _ops_evidence("travel_site_surface_coverage.json"),
            "reason": (
                "TravelSite surface_coverage inventory present; full Gate A live matrix still open"
                if _ops_evidence("travel_site_surface_coverage.json")
                else "No TravelSite surface coverage inventory"
            ),
        },
        "load_test": {
            "ready": _ops_evidence("local_load_probe.json"),
            "reason": (
                "Local API load probe present; controlled soak / prod-like load still open"
                if _ops_evidence("local_load_probe.json")
                else "No load-test suite or drill artifacts established"
            ),
        },
        "controlled_soak": {
            "ready": _ops_evidence("controlled_soak_drill.json"),
            "reason": (
                "Controlled AdminPortal soak evidence present; hosted/prod-like load still open"
                if _ops_evidence("controlled_soak_drill.json")
                else "No controlled fixture soak evidence"
            ),
        },
        "incident_runbook": {
            "ready": (ROOT / "docs" / "INCIDENT_RUNBOOK.md").is_file()
            or _ops_evidence("incident_tabletop_stub.json"),
            "reason": (
                "Incident runbook + stub tabletop present; live paging/restore tabletop still open"
                if (ROOT / "docs" / "INCIDENT_RUNBOOK.md").is_file()
                or _ops_evidence("incident_tabletop_stub.json")
                else "Operator docs exist; dedicated incident runbook drills not established"
            ),
        },
        "ops_drill_checklist": _file_check(
            "docs/OPS_DRILL_CHECKLIST.md",
            ready_reason="Checklist documents required Gate H drills (drills themselves still open)",
            missing_reason="docs/OPS_DRILL_CHECKLIST.md missing",
        ),
        "ci_rollback_rehearsal": {
            "ready": _ops_evidence("ci_rollback_rehearsal.json"),
            "reason": (
                "Offline CI/deploy rollback rehearsal present; live hosted rollback still open"
                if _ops_evidence("ci_rollback_rehearsal.json")
                else "No CI/deploy rollback rehearsal evidence"
            ),
        },
        "paging_rehearsal": {
            "ready": _ops_evidence("paging_rehearsal.json"),
            "reason": (
                "Loopback paging rehearsal present; live hosted on-call/paging still open"
                if _ops_evidence("paging_rehearsal.json")
                else "No paging rehearsal evidence"
            ),
        },
        "failure_matrix_drill": {
            "ready": _ops_evidence("failure_matrix_drill.json"),
            "reason": (
                "Offline failure taxonomy matrix present; live failure matrix still open"
                if _ops_evidence("failure_matrix_drill.json")
                else "No failure taxonomy matrix evidence"
            ),
        },
        "healing_regression_drill": {
            "ready": _ops_evidence("healing_regression_drill.json"),
            "reason": (
                "Offline healing regression suite present; production healing still open"
                if _ops_evidence("healing_regression_drill.json")
                else "No healing regression suite evidence"
            ),
        },
        "api_version_contract": {
            "ready": _ops_evidence("api_version_contract.json"),
            "reason": (
                "API version contract drill present; live hosted SSO still open"
                if _ops_evidence("api_version_contract.json")
                else "No API version contract evidence"
            ),
        },
        "pg_tenancy_drill": {
            "ready": _ops_evidence("pg_tenancy_drill.json"),
            "reason": (
                "Postgres tenancy helper drill present; Studio SSO ACLs still open"
                if _ops_evidence("pg_tenancy_drill.json")
                else "No Postgres tenancy helper evidence"
            ),
        },
        "audit_export_drill": {
            "ready": _ops_evidence("audit_export_drill.json"),
            "reason": (
                "Tenant-scoped audit export evidence present; Studio SSO / review still open"
                if _ops_evidence("audit_export_drill.json")
                else "No audit export drill evidence"
            ),
        },
        "dashboard_auth_matrix_drill": {
            "ready": _ops_evidence("dashboard_auth_matrix_drill.json"),
            "reason": (
                "Dashboard auth mode matrix evidence present; live hosted IdP SSO still open"
                if _ops_evidence("dashboard_auth_matrix_drill.json")
                else "No dashboard auth matrix drill evidence"
            ),
        },
        "approvals_drill": {
            "ready": _ops_evidence("approvals_drill.json"),
            "reason": (
                "Approvals enqueue→decide evidence present; live hosted SSO still open"
                if _ops_evidence("approvals_drill.json")
                else "No approvals drill evidence"
            ),
        },
        "sso_contract_drill": {
            "ready": _ops_evidence("sso_contract_drill.json"),
            "reason": (
                "OIDC/hosting env contract snapshot present; live hosted IdP SSO still open"
                if _ops_evidence("sso_contract_drill.json")
                else "No SSO contract drill evidence"
            ),
        },
        "incident_tabletop_drill": {
            "ready": (
                _ops_evidence("incident_tabletop_drill.json")
                or _ops_evidence("incident_tabletop_stub.json")
            ),
            "reason": (
                "Incident tabletop cross-check present; live hosted on-call still open"
                if (
                    _ops_evidence("incident_tabletop_drill.json")
                    or _ops_evidence("incident_tabletop_stub.json")
                )
                else "No incident tabletop drill evidence"
            ),
        },
        "lifecycle_cleanup_drill": {
            "ready": _ops_evidence("lifecycle_cleanup_drill.json"),
            "reason": (
                "Offline lifecycle cleanup drill present; live portal cleanup paths still open"
                if _ops_evidence("lifecycle_cleanup_drill.json")
                else "No lifecycle cleanup drill evidence"
            ),
        },
        "admin_portal_lifecycle_drill": {
            "ready": _ops_evidence("admin_portal_lifecycle_drill.json"),
            "reason": (
                "AdminPortal create→remote_delete cleanup evidence present; "
                "broader live portal paths still open"
                if _ops_evidence("admin_portal_lifecycle_drill.json")
                else "No AdminPortal lifecycle cleanup drill evidence"
            ),
        },
        "oracle_spec_drill": {
            "ready": _ops_evidence("oracle_spec_drill.json"),
            "reason": (
                "Approved-spec oracle bind evidence present; broader live portal oracles still open"
                if _ops_evidence("oracle_spec_drill.json")
                else "No oracle-spec drill evidence"
            ),
        },
        "demo_store_cart_lifecycle_drill": {
            "ready": _ops_evidence("demo_store_cart_lifecycle_drill.json"),
            "reason": (
                "DemoStore cart add→remove cleanup evidence present; broader live portal paths still open"
                if _ops_evidence("demo_store_cart_lifecycle_drill.json")
                else "No DemoStore cart lifecycle drill evidence"
            ),
        },
        "swarm_control_drill": {
            "ready": _ops_evidence("swarm_control_drill.json"),
            "reason": (
                "Swarm claim/checkpoint/cancel drill present; product-wide supervisor review still open"
                if _ops_evidence("swarm_control_drill.json")
                else "No swarm control drill evidence"
            ),
        },
        "swarm_retry_drill": {
            "ready": _ops_evidence("swarm_retry_drill.json"),
            "reason": (
                "Swarm lease-expiry→retry_wait drill present; product-wide supervisor review still open"
                if _ops_evidence("swarm_retry_drill.json")
                else "No swarm retry drill evidence"
            ),
        },
        "device_matrix_drill": {
            "ready": _ops_evidence("device_matrix_drill.json"),
            "reason": (
                "Combined device matrix snapshot present; full Appium product matrix still open"
                if _ops_evidence("device_matrix_drill.json")
                else "No combined device matrix snapshot evidence"
            ),
        },
        "android_emulator_smoke_drill": {
            "ready": _ops_evidence("android_emulator_smoke_drill.json"),
            "reason": (
                "Live API24 emulator smoke evidence present; full Appium product matrix still open"
                if _ops_evidence("android_emulator_smoke_drill.json")
                else "No Android emulator smoke drill evidence"
            ),
        },
        "android_appium_product_matrix_drill": {
            "ready": _ops_evidence("android_appium_product_matrix_drill.json"),
            "reason": (
                "Live Appium product matrix (system + ApiDemos APK) present; "
                "broad multi-device CI matrix artifacts still open"
                if _ops_evidence("android_appium_product_matrix_drill.json")
                else "No Android Appium product matrix drill evidence"
            ),
        },
        "android_appium_ci_contract": {
            "ready": _ops_evidence("android_appium_ci_contract.json"),
            "reason": (
                "Appium CI artifact contract documented; ubuntu+KVM multi-device job still open"
                if _ops_evidence("android_appium_ci_contract.json")
                else "No Appium CI contract evidence"
            ),
        },
        "multi_browser_portfolio_suite_drill": {
            "ready": _ops_evidence("multi_browser_portfolio_suite_drill.json"),
            "reason": (
                "Live Chromium/Firefox/WebKit DemoStore portfolio suite present; "
                "hosted multi-browser CI still open"
                if _ops_evidence("multi_browser_portfolio_suite_drill.json")
                else "No multi-browser portfolio suite evidence"
            ),
        },
        "loopback_sso_drill": {
            "ready": _ops_evidence("loopback_sso_drill.json"),
            "reason": (
                "Loopback OIDC JWT signature drill present; hosted IdP SSO still open"
                if _ops_evidence("loopback_sso_drill.json")
                else "No loopback SSO drill evidence"
            ),
        },
        "demo_store_healing_live_drill": {
            "ready": _ops_evidence("demo_store_healing_live_drill.json"),
            "reason": (
                "Live DemoStore healing policy drill present; production healing suite still open"
                if _ops_evidence("demo_store_healing_live_drill.json")
                else "No DemoStore healing live drill evidence"
            ),
        },
        "locale_portfolio_drill": {
            "ready": _ops_evidence("locale_portfolio_drill.json"),
            "reason": (
                "DemoStore locale portfolio evidence present; broad live multi-browser CI still open"
                if _ops_evidence("locale_portfolio_drill.json")
                else "No locale portfolio drill evidence"
            ),
        },
        "security_portfolio_drill": {
            "ready": _ops_evidence("security_portfolio_drill.json"),
            "reason": (
                "DemoStore passive security portfolio evidence present; broad live CI still open"
                if _ops_evidence("security_portfolio_drill.json")
                else "No security portfolio drill evidence"
            ),
        },
        "a11y_portfolio_drill": {
            "ready": _ops_evidence("a11y_portfolio_drill.json"),
            "reason": (
                "DemoStore a11y portfolio evidence present; broad live CI still open"
                if _ops_evidence("a11y_portfolio_drill.json")
                else "No a11y portfolio drill evidence"
            ),
        },
        "perf_portfolio_drill": {
            "ready": _ops_evidence("perf_portfolio_drill.json"),
            "reason": (
                "DemoStore performance portfolio evidence present; broad live CI still open"
                if _ops_evidence("perf_portfolio_drill.json")
                else "No performance portfolio drill evidence"
            ),
        },
        "visual_portfolio_drill": {
            "ready": _ops_evidence("visual_portfolio_drill.json"),
            "reason": (
                "DemoStore first-run visual portfolio evidence present; broad live CI still open"
                if _ops_evidence("visual_portfolio_drill.json")
                else "No visual portfolio drill evidence"
            ),
        },
        "compatibility_portfolio_drill": {
            "ready": _ops_evidence("compatibility_portfolio_drill.json"),
            "reason": (
                "DemoStore desktop+mobile compatibility portfolio evidence present; "
                "broad live multi-browser CI still open"
                if _ops_evidence("compatibility_portfolio_drill.json")
                else "No compatibility portfolio drill evidence"
            ),
        },
    }
    ready = [name for name, row in checks.items() if row.get("ready")]
    missing = [name for name, row in checks.items() if not row.get("ready")]
    return {
        "gate_h_complete": False,
        "ready": ready,
        "missing": missing,
        "checks": checks,
    }
