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
        "lifecycle_cleanup_drill": {
            "ready": _ops_evidence("lifecycle_cleanup_drill.json"),
            "reason": (
                "Offline lifecycle cleanup drill present; live portal cleanup paths still open"
                if _ops_evidence("lifecycle_cleanup_drill.json")
                else "No lifecycle cleanup drill evidence"
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
        "device_matrix_drill": {
            "ready": _ops_evidence("device_matrix_drill.json"),
            "reason": (
                "Combined device matrix snapshot present; live emulator/API24+ still open"
                if _ops_evidence("device_matrix_drill.json")
                else "No combined device matrix snapshot evidence"
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
    }
    ready = [name for name, row in checks.items() if row.get("ready")]
    missing = [name for name, row in checks.items() if not row.get("ready")]
    return {
        "gate_h_complete": False,
        "ready": ready,
        "missing": missing,
        "checks": checks,
    }
