"""Gate G: live Postgres migration + tenant isolation drill via psql CLI.

Uses the system ``psql`` client so we do not require a Python driver dependency.
Gate G stays incomplete until independent review + full multi-tenant product path.
"""
# ruff: noqa: S608
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "migrations"
EVIDENCE = ROOT / "docs" / "ops-evidence" / "postgres_isolation_drill.json"
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9._-]+$")


def _dsn() -> str:
    return (
        os.getenv("POSTGRES_URL")
        or os.getenv("QPILOT_DB_URL")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()


def _psql_env(dsn: str) -> tuple[dict, list[str]]:
    """Build env + argv for psql from a postgresql:// URL or libpq keywords."""
    env = dict(os.environ)
    args = ["psql", "-v", "ON_ERROR_STOP=1", "-t", "-A"]
    if dsn.startswith(("postgres://", "postgresql://")):
        parsed = urlparse(dsn)
        if parsed.password:
            env["PGPASSWORD"] = parsed.password
        if parsed.username:
            args += ["-U", parsed.username]
        if parsed.hostname:
            args += ["-h", parsed.hostname]
        if parsed.port:
            args += ["-p", str(parsed.port)]
        db = (parsed.path or "/").lstrip("/") or "postgres"
        args += ["-d", db]
    else:
        args += [dsn]
    return env, args


def run_psql(sql: str, *, dsn: str | None = None) -> subprocess.CompletedProcess:
    target = (dsn or _dsn()).strip()
    if not target:
        raise RuntimeError("POSTGRES_URL / DATABASE_URL not set")
    env, args = _psql_env(target)
    return subprocess.run(
        args + ["-c", sql],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def apply_migrations_psql(*, dsn: str | None = None) -> dict:
    """Apply migrations/*.sql through psql."""
    target = (dsn or _dsn()).strip()
    files = sorted(p for p in MIGRATIONS.glob("*.sql") if p.is_file())
    applied = []
    for file in files:
        version = file.name
        if not _SAFE_VERSION.match(version):
            return {"ok": False, "reason": f"unsafe migration name: {version}", "applied": applied}
        ensure = run_psql(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);",
            dsn=target,
        )
        if ensure.returncode != 0:
            return {"ok": False, "reason": ensure.stderr.strip()[:300], "applied": applied}

        exists = run_psql(
            "SELECT 1 FROM schema_migrations WHERE version='" + version + "';",
            dsn=target,
        )
        if exists.returncode == 0 and exists.stdout.strip() == "1":
            continue
        env, args = _psql_env(target)
        proc = subprocess.run(
            args + ["-f", str(file)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if proc.returncode != 0:
            return {"ok": False, "reason": proc.stderr.strip()[:300], "applied": applied, "file": file.name}
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        mark = run_psql(
            "INSERT INTO schema_migrations(version, applied_at) VALUES ('"
            + version + "', '" + stamp + "') ON CONFLICT (version) DO NOTHING;",
            dsn=target,
        )
        if mark.returncode != 0:
            return {"ok": False, "reason": mark.stderr.strip()[:300], "applied": applied}
        applied.append(file.name)
    return {"ok": True, "applied": applied, "files": [f.name for f in files]}


def isolation_drill(*, dsn: str | None = None) -> dict:
    """Create two tenants and prove run_index rows do not cross-read by tenant filter."""
    target = (dsn or _dsn()).strip()
    evidence: dict = {
        "gate_g_complete": False,
        "drill": "postgres_tenant_isolation",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backend": "postgres",
        "ok": False,
        "reason": "",
    }
    if not target:
        evidence["reason"] = "POSTGRES_URL not set"
        return evidence
    mig = apply_migrations_psql(dsn=target)
    evidence["migrations"] = mig
    if not mig.get("ok"):
        evidence["reason"] = mig.get("reason") or "migration failed"
        return evidence

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Fixed drill identifiers; stamp is locally generated.
    setup_sql = (
        "DELETE FROM run_index WHERE run_id LIKE 'drill-%';"
        "DELETE FROM principals WHERE principal_id LIKE 'drill-%';"
        "DELETE FROM tenants WHERE tenant_id LIKE 'drill-%';"
        "INSERT INTO tenants(tenant_id, name, created_at) VALUES "
        f"('drill-a', 'Tenant A', '{stamp}'), ('drill-b', 'Tenant B', '{stamp}');"
        "INSERT INTO principals(principal_id, tenant_id, email, role, created_at) VALUES "
        f"('drill-pa', 'drill-a', 'a@example.test', 'admin', '{stamp}'), "
        f"('drill-pb', 'drill-b', 'b@example.test', 'viewer', '{stamp}');"
        "INSERT INTO run_index(run_id, tenant_id, source, verdict, created_at) VALUES "
        f"('drill-run-a', 'drill-a', 'https://a.test', 'Ready', '{stamp}'), "
        f"('drill-run-b', 'drill-b', 'https://b.test', 'Not Ready', '{stamp}');"
    )
    setup = run_psql(setup_sql, dsn=target)
    if setup.returncode != 0:
        evidence["reason"] = setup.stderr.strip()[:300]
        return evidence

    only_a = run_psql(
        "SELECT run_id FROM run_index WHERE tenant_id='drill-a' ORDER BY run_id;",
        dsn=target,
    )
    only_b = run_psql(
        "SELECT run_id FROM run_index WHERE tenant_id='drill-b' ORDER BY run_id;",
        dsn=target,
    )
    cross = run_psql(
        "SELECT COUNT(*) FROM run_index WHERE tenant_id='drill-a' AND run_id='drill-run-b';",
        dsn=target,
    )
    rows_a = [line for line in only_a.stdout.splitlines() if line.strip()]
    rows_b = [line for line in only_b.stdout.splitlines() if line.strip()]
    cross_count = (cross.stdout or "").strip()
    ok = (
        only_a.returncode == 0
        and only_b.returncode == 0
        and rows_a == ["drill-run-a"]
        and rows_b == ["drill-run-b"]
        and cross_count == "0"
    )
    evidence.update({
        "ok": ok,
        "tenant_a_runs": rows_a,
        "tenant_b_runs": rows_b,
        "cross_tenant_hits": cross_count,
        "reason": (
            "Live Postgres migration + tenant-filtered run_index isolation verified via psql; "
            "product-wide multi-tenant Studio path + independent review still open"
            if ok else
            "Isolation assertions failed"
        ),
    })
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    art = ROOT / "artifacts" / "ops" / "postgres_isolation_drill.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
