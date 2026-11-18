"""Gate G enterprise readiness probe. Reports configured backends without claiming they work.

Postgres / Redis / remote MinIO remain optional. Local SQLite durable queue and
local object store keep the product usable offline.
"""
from __future__ import annotations

import os

from .api_versioning import SUPPORTED
from .migrate import migration_status
from .object_store import open_object_store
from .queue_backend import open_durable_queue
from .rbac import ROLES


def _present(name: str) -> str:
    return (os.getenv(name) or os.getenv(name.replace("QPILOT_", "BLOWAI_")) or "").strip()


def readiness() -> dict:
    """Snapshot of enterprise dependencies. Secrets are never returned."""
    postgres = _present("POSTGRES_URL") or _present("QPILOT_DB_URL") or _present("DATABASE_URL")
    redis = _present("REDIS_URL") or _present("QPILOT_REDIS_URL")
    object_uri = _present("OBJECT_STORE_URI") or _present("MINIO_URL")
    store = open_object_store(object_uri or None)
    queue = open_durable_queue(redis or None)
    migrations = migration_status(postgres or None)
    components = {
        "postgres": {
            "configured": bool(postgres),
            "ready": False,
            "migrations": migrations.get("versions") or [],
            "reason": "Postgres URL set but live driver/isolation drill not established" if postgres
            else "Postgres not configured; SQLite migrations can still apply offline",
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
            "ready": bool(queue.get("ready")) and queue.get("backend") == "redis",
            "reason": queue.get("reason") if redis else "Redis not configured; DurableQueue SQLite remains default",
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
            "configured": False,
            "ready": False,
            "reason": "Studio remains HTML/JS under frontend/; React/TS dashboard not established",
        },
    }
    ready = ["rbac", "api_versioning"]
    if components["object_store"]["ready"]:
        ready.append("object_store")
    if components["durable_queue"]["ready"]:
        ready.append("durable_queue")
    if components["schema_migrations"]["ready"]:
        ready.append("schema_migrations")
    missing = [name for name, row in components.items() if not row["ready"]]
    return {
        "gate_g_complete": False,
        "gate_i_complete": False,
        "ready": ready,
        "missing": missing,
        "components": components,
    }
