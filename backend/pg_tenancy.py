"""Gate G: Postgres-backed tenancy helpers via psql (optional when POSTGRES_URL set).

Mirrors the SQLite tenancy_store surface for principals / run_index reads.
Studio SSO + independent review still open. Never marks Gate G complete.
"""
# ruff: noqa: S608  # values are escaped for psql string literals (same pattern as postgres_drill)
from __future__ import annotations

import os
import time

from .postgres_drill import _dsn, apply_migrations_psql, run_psql
from .rbac import allow


def postgres_configured() -> bool:
    return bool(_dsn().strip() or (os.getenv("POSTGRES_URL") or "").strip())


def get_principal_pg(principal_id: str, *, dsn: str | None = None) -> dict | None:
    target = (dsn or _dsn()).strip()
    pid = (principal_id or "").strip()
    if not target or not pid:
        return None
    apply_migrations_psql(dsn=target)
    # Safe: principal_id is single-quoted with escapes for SQL string literal.
    safe = pid.replace("'", "''")
    proc = run_psql(
        "SELECT principal_id || '|' || tenant_id || '|' || COALESCE(email,'') || '|' || COALESCE(role,'') "
        f"FROM principals WHERE principal_id='{safe}' LIMIT 1;",
        dsn=target,
    )
    if proc.returncode != 0:
        return None
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return None
    parts = line[0].split("|", 3)
    if len(parts) < 4:
        return None
    return {
        "principal_id": parts[0],
        "tenant_id": parts[1],
        "email": parts[2],
        "role": parts[3],
    }


def list_runs_for_tenant_pg(tenant_id: str, *, dsn: str | None = None) -> list[dict]:
    target = (dsn or _dsn()).strip()
    tid = (tenant_id or "").strip()
    if not target or not tid:
        return []
    apply_migrations_psql(dsn=target)
    safe = tid.replace("'", "''")
    proc = run_psql(
        "SELECT run_id || '|' || tenant_id || '|' || COALESCE(source,'') || '|' || COALESCE(verdict,'') || '|' || "
        f"COALESCE(created_at,'') FROM run_index WHERE tenant_id='{safe}' ORDER BY created_at DESC;",
        dsn=target,
    )
    if proc.returncode != 0:
        return []
    out = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("|", 4)
        if len(parts) >= 4:
            out.append({
                "run_id": parts[0],
                "tenant_id": parts[1],
                "source": parts[2],
                "verdict": parts[3],
                "created_at": parts[4] if len(parts) > 4 else "",
            })
    return out


def index_run_pg(run_id: str, tenant_id: str, *, source: str = "", verdict: str = "",
                 dsn: str | None = None) -> dict:
    target = (dsn or _dsn()).strip()
    if not target:
        raise RuntimeError("POSTGRES_URL not set")
    apply_migrations_psql(dsn=target)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def q(s: str) -> str:
        return (s or "").replace("'", "''")

    sql = (
        "INSERT INTO run_index(run_id, tenant_id, source, verdict, created_at) VALUES ("
        f"'{q(run_id)}', '{q(tenant_id)}', '{q(source)[:300]}', '{q(verdict)}', '{stamp}') "
        "ON CONFLICT(run_id) DO UPDATE SET source=EXCLUDED.source, verdict=EXCLUDED.verdict "
        "WHERE run_index.tenant_id = EXCLUDED.tenant_id;"
    )
    proc = run_psql(sql, dsn=target)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300] or "index_run_pg failed")
    stored = run_psql(
        f"SELECT tenant_id FROM run_index WHERE run_id='{q(run_id)}' LIMIT 1;",
        dsn=target,
    )
    owner = (stored.stdout or "").strip().splitlines()
    kept = owner[0].strip() if owner else tenant_id
    if kept != tenant_id:
        return {
            "run_id": run_id, "tenant_id": kept, "source": source, "verdict": verdict,
            "backend": "postgres", "ok": False, "reason": "run already belongs to another tenant",
            "gate_g_complete": False,
        }
    return {
        "run_id": run_id, "tenant_id": tenant_id, "source": source, "verdict": verdict,
        "backend": "postgres", "ok": True, "gate_g_complete": False,
    }


def runs_visible_to_principal_pg(principal_id: str, *, dsn: str | None = None) -> dict:
    principal = get_principal_pg(principal_id, dsn=dsn)
    if principal is None:
        return {
            "ok": False,
            "reason": "unknown principal",
            "runs": [],
            "backend": "postgres",
            "gate_g_complete": False,
        }
    if not allow(
        role=principal["role"],
        action="run.read",
        tenant_id=principal["tenant_id"],
        resource_tenant=principal["tenant_id"],
    ).get("allowed"):
        return {
            "ok": False,
            "reason": "role cannot read runs",
            "principal_id": principal_id,
            "tenant_id": principal["tenant_id"],
            "role": principal["role"],
            "runs": [],
            "backend": "postgres",
            "gate_g_complete": False,
        }
    runs = list_runs_for_tenant_pg(principal["tenant_id"], dsn=dsn)
    return {
        "ok": True,
        "reason": "Postgres tenant-scoped runs (Studio SSO still open)",
        "principal_id": principal_id,
        "tenant_id": principal["tenant_id"],
        "role": principal["role"],
        "runs": runs,
        "backend": "postgres",
        "gate_g_complete": False,
    }
