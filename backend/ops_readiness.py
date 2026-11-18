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
        "load_test": {
            "ready": _ops_evidence("local_load_probe.json"),
            "reason": (
                "Local API load probe present; controlled soak / prod-like load still open"
                if _ops_evidence("local_load_probe.json")
                else "No load-test suite or drill artifacts established"
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
    }
    ready = [name for name, row in checks.items() if row.get("ready")]
    missing = [name for name, row in checks.items() if not row.get("ready")]
    return {
        "gate_h_complete": False,
        "ready": ready,
        "missing": missing,
        "checks": checks,
    }
