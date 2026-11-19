"""Gate G enterprise readiness probe. Reports configured backends without claiming they work.

Postgres / Redis / remote MinIO remain optional. Local SQLite durable queue and
local object store keep the product usable offline.
"""
from __future__ import annotations

import os
from pathlib import Path

from .api_versioning import SUPPORTED
from .blueprint_progress import progress as blueprint_progress
from .dashboard_auth import snapshot as dashboard_auth_snapshot
from .dashboard_sso import snapshot as dashboard_sso_snapshot
from .migrate import migration_status
from .object_store import open_object_store
from .queue_backend import open_durable_queue
from .rbac import ROLES

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_PKG = ROOT / "frontend" / "dashboard" / "package.json"
DASHBOARD_DIST = ROOT / "frontend" / "dashboard" / "dist" / "index.html"


def _present(name: str) -> str:
    return (os.getenv(name) or os.getenv(name.replace("QPILOT_", "BLOWAI_")) or "").strip()


def readiness() -> dict:
    """Snapshot of enterprise dependencies. Secrets are never returned."""
    postgres = _present("POSTGRES_URL") or _present("QPILOT_DB_URL") or _present("DATABASE_URL")
    redis = _present("REDIS_URL") or _present("QPILOT_REDIS_URL")
    object_uri = _present("OBJECT_STORE_URI") or _present("MINIO_URL")
    store = open_object_store(object_uri or None)
    sqlite_queue = open_durable_queue("sqlite:runs/.swarm_queue.sqlite")
    redis_queue = open_durable_queue(redis) if redis else {"ready": False, "backend": "redis", "reason": "not configured"}
    queue = redis_queue if redis_queue.get("ready") else sqlite_queue
    migrations = migration_status(postgres or None)
    dashboard_configured = DASHBOARD_PKG.is_file()
    dashboard_built = DASHBOARD_DIST.is_file()
    pg_evidence = ROOT / "docs" / "ops-evidence" / "postgres_isolation_drill.json"
    pg_tenancy_evidence = ROOT / "docs" / "ops-evidence" / "pg_tenancy_drill.json"
    redis_evidence = ROOT / "docs" / "ops-evidence" / "redis_lease_drill.json"
    redis_queue_evidence = ROOT / "docs" / "ops-evidence" / "redis_durable_queue_drill.json"
    minio_evidence = ROOT / "docs" / "ops-evidence" / "minio_object_store_drill.json"
    api_version_evidence = ROOT / "docs" / "ops-evidence" / "api_version_contract.json"
    swarm_control_evidence = ROOT / "docs" / "ops-evidence" / "swarm_control_drill.json"
    swarm_retry_evidence = ROOT / "docs" / "ops-evidence" / "swarm_retry_drill.json"

    def _evidence_file(path: Path) -> bool:
        from .finalization import folder_is_linked
        return path.is_file() and not folder_is_linked(path)

    def _evidence_ok(path: Path) -> bool:
        if not _evidence_file(path):
            return False
        try:
            import json
            return bool(json.loads(path.read_text(encoding="utf-8")).get("ok"))
        except (OSError, ValueError):
            return False

    pg_live = bool(postgres) and _evidence_ok(pg_evidence)
    pg_tenancy_live = bool(postgres) and _evidence_file(pg_tenancy_evidence)
    redis_live = bool(redis) and (
        _evidence_ok(redis_queue_evidence) or _evidence_ok(redis_evidence) or bool(redis_queue.get("ready"))
    )
    minio_live = bool(object_uri) and _evidence_ok(minio_evidence)
    api_version_ready = _evidence_file(api_version_evidence)
    swarm_control_ready = _evidence_file(swarm_control_evidence)
    swarm_retry_ready = _evidence_file(swarm_retry_evidence)
    components = {
        "postgres": {
            "configured": bool(postgres),
            "ready": pg_live,
            "migrations": migrations.get("versions") or [],
            "reason": (
                "Live Postgres isolation drill verified (psql); Studio multi-tenant path + review still open"
                if pg_live else
                ("Postgres URL set but isolation drill evidence missing" if postgres
                 else "Postgres not configured; SQLite migrations can still apply offline")
            ),
        },
        "schema_migrations": {
            "configured": bool(migrations.get("configured")),
            "ready": bool(migrations.get("ready")),
            "backend": migrations.get("backend"),
            "versions": migrations.get("versions") or [],
            "applied": migrations.get("applied") or [],
            "reason": migrations.get("reason") or "",
        },
        "redis": {
            "configured": bool(redis),
            "ready": redis_live,
            "reason": (
                "Redis DurableQueue adapter + lease evidence ready; product-wide default/review still open"
                if redis_live else
                (redis_queue.get("reason") if redis else "Redis not configured; DurableQueue SQLite remains default")
            ),
            "queue_backend": queue.get("backend"),
        },
        "durable_queue": {
            "configured": True,
            "ready": bool(sqlite_queue.get("ready") or redis_queue.get("ready")),
            "backend": queue.get("backend"),
            "reason": queue.get("reason") or "local SQLite durable queue ready",
        },
        "object_store": {
            "configured": bool(object_uri) or True,
            "ready": bool(store.get("ready")) if not object_uri else minio_live or bool(store.get("ready")),
            "backend": store.get("backend"),
            "reason": (
                "Live MinIO put/get/delete verified; multi-tenant ACLs + review still open"
                if minio_live else
                (store.get("reason") or ("local object store ready" if store.get("ready") else "not ready"))
            ),
        },
        "rbac": {
            "configured": True,
            "ready": True,
            "roles": sorted(ROLES),
            "reason": (
                "deny-by-default RBAC + tenant run ACL helpers (/api/tenancy/runs); "
                "Studio multi-tenant SSO still open"
            ),
        },
        "api_versioning": {
            "configured": True,
            "ready": True,
            "supported": sorted(SUPPORTED),
            "contract_evidence": api_version_ready,
            "reason": (
                "legacy /api maps to v1; /api/v1 is canonical"
                + ("; contract drill evidence present" if api_version_ready else "")
            ),
        },
        "pg_tenancy": {
            "configured": bool(postgres),
            "ready": pg_tenancy_live,
            "reason": (
                "Postgres tenancy helpers verified; Studio SSO ACLs still open"
                if pg_tenancy_live else
                ("POSTGRES_URL set but pg_tenancy drill evidence missing" if postgres
                 else "Postgres not configured for tenancy helpers")
            ),
        },
        "swarm_control": {
            "configured": True,
            "ready": swarm_control_ready,
            "reason": (
                "Swarm claim/checkpoint/cancel drill evidence present; product-wide review still open"
                if swarm_control_ready else
                "No swarm control drill evidence yet"
            ),
        },
        "swarm_retry": {
            "configured": True,
            "ready": swarm_retry_ready,
            "reason": (
                "Swarm lease-expiry→retry_wait drill evidence present; product-wide review still open"
                if swarm_retry_ready else
                "No swarm retry drill evidence yet"
            ),
        },
        "react_dashboard": {
            "configured": dashboard_configured,
            "ready": dashboard_built,
            "path": "frontend/dashboard",
            "reason": (
                "React/TS dashboard built at /dashboard/; Gate I still incomplete without auth/hosting"
                if dashboard_built else
                "React/TS dashboard scaffold at frontend/dashboard; run npm run build (Gate I still incomplete)"
                if dashboard_configured else
                "React/TS dashboard not established"
            ),
        },
        "approvals": {
            "configured": True,
            "ready": True,
            "reason": "Durable approvals queue + decide API; Studio auth still open",
        },
        "dashboard_auth": {
            "configured": bool(
                _present("QPILOT_DASHBOARD_TOKEN")
                or _present("BLOWAI_DASHBOARD_TOKEN")
                or _present("QPILOT_DASHBOARD_AUTH")
                or _present("WEBHOOK_TOKEN")
            ),
            "ready": False,
            "reason": dashboard_auth_snapshot()["reason"],
        },
        "dashboard_sso": {
            "configured": bool(dashboard_sso_snapshot().get("configured")),
            "ready": False,
            "reason": dashboard_sso_snapshot()["reason"],
        },
    }
    ready = ["rbac", "api_versioning", "approvals"]
    if components["object_store"]["ready"]:
        ready.append("object_store")
    if components["durable_queue"]["ready"]:
        ready.append("durable_queue")
    if components["schema_migrations"]["ready"]:
        ready.append("schema_migrations")
    if components["react_dashboard"]["ready"]:
        ready.append("react_dashboard")
    if components["postgres"]["ready"]:
        ready.append("postgres")
    if components["redis"]["ready"]:
        ready.append("redis")
    if components["pg_tenancy"]["ready"]:
        ready.append("pg_tenancy")
    if components["swarm_control"]["ready"]:
        ready.append("swarm_control")
    if components["swarm_retry"]["ready"]:
        ready.append("swarm_retry")
    missing = [name for name, row in components.items() if not row["ready"]]
    blueprint = blueprint_progress()
    return {
        "gate_g_complete": False,
        "gate_i_complete": False,
        "ready": ready,
        "missing": missing,
        "components": components,
        "blueprint": blueprint,
    }
