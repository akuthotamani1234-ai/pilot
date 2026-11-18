"""Gate G offline SQLite tenancy helpers (tenants / principals / run_index).

Complements audit_store. Does not claim live Postgres isolation by itself.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .migrate import apply_migrations
from .rbac import allow

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "runs" / ".qpilot.sqlite"


def _connect(path: Path) -> sqlite3.Connection:
    apply_migrations(f"sqlite:{path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def upsert_tenant(tenant_id: str, name: str, *, db_path: str | Path | None = None) -> dict:
    path = Path(db_path) if db_path else DEFAULT_DB
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO tenants(tenant_id, name, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(tenant_id) DO UPDATE SET name=excluded.name",
            (tenant_id, name, stamp),
        )
        conn.commit()
    return {"tenant_id": tenant_id, "name": name, "created_at": stamp}


def upsert_principal(principal_id: str, tenant_id: str, email: str, role: str,
                     *, db_path: str | Path | None = None) -> dict:
    path = Path(db_path) if db_path else DEFAULT_DB
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO principals(principal_id, tenant_id, email, role, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(principal_id) DO UPDATE SET email=excluded.email, role=excluded.role, "
            "tenant_id=excluded.tenant_id",
            (principal_id, tenant_id, email, role, stamp),
        )
        conn.commit()
    return {"principal_id": principal_id, "tenant_id": tenant_id, "email": email, "role": role}


def index_run(run_id: str, tenant_id: str, *, source: str = "", verdict: str = "",
              db_path: str | Path | None = None) -> dict:
    path = Path(db_path) if db_path else DEFAULT_DB
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO run_index(run_id, tenant_id, source, verdict, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET tenant_id=excluded.tenant_id, source=excluded.source, "
            "verdict=excluded.verdict",
            (run_id, tenant_id, source, verdict, stamp),
        )
        conn.commit()
    return {"run_id": run_id, "tenant_id": tenant_id, "source": source, "verdict": verdict}


def list_runs_for_tenant(tenant_id: str, *, db_path: str | Path | None = None) -> list[dict]:
    path = Path(db_path) if db_path else DEFAULT_DB
    if not path.is_file():
        return []
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT run_id, tenant_id, source, verdict, created_at FROM run_index "
            "WHERE tenant_id=? ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def can_read_run(*, role: str, actor_tenant: str, run_tenant: str) -> bool:
    """Deny cross-tenant reads (RBAC + tenant check)."""
    verdict = allow(role=role, action="run.read", tenant_id=actor_tenant, resource_tenant=run_tenant)
    return bool(verdict.get("allowed"))
