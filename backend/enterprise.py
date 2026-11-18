"""Gate G enterprise readiness probe. Reports configured backends without claiming they work.

Postgres / Redis / remote MinIO remain optional. Local SQLite durable queue and
local object store keep the product usable offline.
"""
from __future__ import annotations

import os
from pathlib import Path

from .api_versioning import SUPPORTED
from .blueprint_progress import progress as blueprint_progress
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
    # Durable queue stays on SQLite by default even when REDIS_URL is set (adapter still open).
    queue = open_durable_queue("sqlite:runs/.swarm_queue.sqlite")
    migrations = migration_status(postgres or None)
    dashboard_configured = DASHBOARD_PKG.is_file()
    dashboard_built = DASHBOARD_DIST.is_file()
    pg_evidence = ROOT / "docs" / "ops-evidence" / "postgres_isolation_drill.json"
    redis_evidence = ROOT / "docs" / "ops-evidence" / "redis_lease_drill.json"

    def _evidence_ok(path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            import json
            return bool(json.loads(path.read_text(encoding="utf-8")).get("ok"))
        except (OSError, ValueError):
            return False

    pg_live = bool(postgres) and _evidence_ok(pg_evidence)
    redis_live = bool(redis) and _evidence_ok(redis_evidence)
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
                "Live Redis lease drill verified (redis-cli); DurableQueue Redis adapter still open"
                if redis_live else
                (queue.get("reason") if redis else "Redis not configured; DurableQueue SQLite remains default")
            ),
            "queue_backend": queue.get("backend"),
        },
        "durable_queue": {
            "configured": True,
            "ready": bool(queue.get("ready")),
            "backend": queue.get("backend"),
            "reason": queue.get("reason") or "local SQLite durable queue ready",
        },
        "object_store": {
            "configured": bool(object_uri) or True,
            "ready": bool(store.get("ready")),
            "backend": store.get("backend"),
            "reason": store.get("reason") or ("local object store ready" if store.get("ready") else "not ready"),
        },
        "rbac": {
            "configured": True,
            "ready": True,
            "roles": sorted(ROLES),
            "reason": "deny-by-default helper available; Studio multi-tenant auth not wired",
        },
        "api_versioning": {
            "configured": True,
            "ready": True,
            "supported": sorted(SUPPORTED),
            "reason": "legacy /api maps to v1; /api/v1 is canonical",
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
                _present("QPILOT_DASHBOARD_TOKEN") or _present("BLOWAI_DASHBOARD_TOKEN")
            ),
            "ready": False,
            "reason": (
                "Optional bearer token configured; SSO/multi-tenant hosting still open"
                if (_present("QPILOT_DASHBOARD_TOKEN") or _present("BLOWAI_DASHBOARD_TOKEN"))
                else "Dashboard token unset; approvals open on localhost (SSO/hosting still open)"
            ),
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
