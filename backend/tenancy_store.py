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
        row = conn.execute(
            "SELECT tenant_id FROM run_index WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is not None and str(row["tenant_id"]) != tenant_id:
            return {
                "run_id": run_id,
                "tenant_id": str(row["tenant_id"]),
                "source": source,
                "verdict": verdict,
                "ok": False,
                "reason": "run already belongs to another tenant",
                "gate_g_complete": False,
            }
        conn.execute(
            "INSERT INTO run_index(run_id, tenant_id, source, verdict, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET source=excluded.source, verdict=excluded.verdict",
            (run_id, tenant_id, source, verdict, stamp),
        )
        conn.commit()
    return {
        "run_id": run_id, "tenant_id": tenant_id, "source": source, "verdict": verdict,
        "ok": True, "gate_g_complete": False,
    }


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


def get_principal(principal_id: str, *, db_path: str | Path | None = None) -> dict | None:
    """Lookup one principal row, or None.

    When ``POSTGRES_URL`` is set and no explicit ``db_path`` is passed, prefer
    the live Postgres tenancy tables (Gate G still incomplete).
    """
    if db_path is None:
        try:
            from .pg_tenancy import get_principal_pg, postgres_configured
            if postgres_configured():
                row = get_principal_pg(principal_id)
                if row is not None:
                    return row
        except Exception:
            pass
    path = Path(db_path) if db_path else DEFAULT_DB
    if not path.is_file():
        return None
    pid = (principal_id or "").strip()
    if not pid:
        return None
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT principal_id, tenant_id, email, role, created_at FROM principals WHERE principal_id=?",
            (pid,),
        ).fetchone()
    return dict(row) if row is not None else None


def get_run_tenant(run_id: str, *, db_path: str | Path | None = None) -> str | None:
    path = Path(db_path) if db_path else DEFAULT_DB
    if not path.is_file():
        return None
    rid = (run_id or "").strip()
    if not rid:
        return None
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT tenant_id FROM run_index WHERE run_id=?",
            (rid,),
        ).fetchone()
    return str(row["tenant_id"]) if row is not None else None


def assert_run_access(
    *,
    principal_id: str,
    run_id: str,
    db_path: str | Path | None = None,
    audit: bool = True,
) -> dict:
    """Whether principal may read ``run_id``. Cross-tenant denials are audited when ``audit``."""
    principal = get_principal(principal_id, db_path=db_path)
    if principal is None:
        return {"allowed": False, "reason": "unknown principal", "principal_id": principal_id, "run_id": run_id}
    run_tenant = get_run_tenant(run_id, db_path=db_path)
    if run_tenant is None:
        return {
            "allowed": False,
            "reason": "unknown run",
            "principal_id": principal_id,
            "run_id": run_id,
            "tenant_id": principal["tenant_id"],
        }
    ok = can_read_run(
        role=principal["role"],
        actor_tenant=principal["tenant_id"],
        run_tenant=run_tenant,
    )
    detail = f"run={run_id} resource_tenant={run_tenant}"
    if audit and not ok:
        from .audit_store import record_audit
        record_audit(
            actor=principal_id,
            action="run.read",
            allowed=False,
            tenant_id=principal["tenant_id"],
            detail=detail,
            db_path=db_path,
        )
    return {
        "allowed": ok,
        "reason": "" if ok else "tenant isolation",
        "principal_id": principal_id,
        "run_id": run_id,
        "tenant_id": principal["tenant_id"],
        "role": principal["role"],
        "resource_tenant": run_tenant,
    }


def runs_visible_to_principal(principal_id: str, *, db_path: str | Path | None = None) -> dict:
    """Tenant-scoped run list for a principal (Gate G ACL helper; Studio SSO still open)."""
    if db_path is None:
        try:
            from .pg_tenancy import postgres_configured, runs_visible_to_principal_pg
            if postgres_configured():
                return runs_visible_to_principal_pg(principal_id)
        except Exception:
            pass
    principal = get_principal(principal_id, db_path=db_path)
    if principal is None:
        return {
            "ok": False,
            "reason": "unknown principal",
            "runs": [],
            "gate_g_complete": False,
        }
    if not can_read_run(role=principal["role"], actor_tenant=principal["tenant_id"],
                        run_tenant=principal["tenant_id"]):
        return {
            "ok": False,
            "reason": "role cannot read runs",
            "principal_id": principal_id,
            "tenant_id": principal["tenant_id"],
            "role": principal["role"],
            "runs": [],
            "gate_g_complete": False,
        }
    runs = list_runs_for_tenant(principal["tenant_id"], db_path=db_path)
    return {
        "ok": True,
        "reason": "tenant-scoped runs (multi-tenant Studio SSO still open)",
        "principal_id": principal_id,
        "tenant_id": principal["tenant_id"],
        "role": principal["role"],
        "runs": runs,
        "gate_g_complete": False,
    }
