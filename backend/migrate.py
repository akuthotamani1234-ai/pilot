"""Apply Gate G SQL migrations.

SQLite applies offline for schema proof. A Postgres URL is recognized but not
silently marked ready until a live driver + isolation drill exists.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "migrations"


def list_migrations() -> list[Path]:
    from .finalization import folder_is_linked
    if folder_is_linked(MIGRATIONS) or not MIGRATIONS.is_dir():
        return []
    return sorted(p for p in MIGRATIONS.glob("*.sql") if p.is_file() and not folder_is_linked(p))


def sqlite_path_is_linked(path: str | Path) -> bool:
    """True when the database file, or a folder on the way to it, is a link."""
    path = Path(path)
    if path.is_absolute():
        cursor = Path(path.anchor)
        parts = path.parts[1:]
    else:
        cursor = Path()
        parts = path.parts
    for part in parts:
        if not part or part in {".", ".."}:
            return True
        cursor = cursor / part
        if cursor.is_symlink():
            return True
        if not cursor.exists():
            return False
    return False


def _sqlite_path(uri: str) -> Path:
    raw = uri.strip()
    for prefix in ("sqlite:///", "sqlite://", "sqlite:", "file:", "local:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    return Path(raw or "runs/.qpilot.sqlite")


def apply_sqlite(path: str | Path) -> dict:
    """Apply all *.sql migrations to a SQLite database file."""
    db_path = Path(path)
    if sqlite_path_is_linked(db_path):
        return {"ready": False, "backend": "sqlite", "path": str(db_path), "applied": [], "versions": [],
                "reason": "The tenant database is a link."}
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path_is_linked(db_path):
        return {"ready": False, "backend": "sqlite", "path": str(db_path), "applied": [], "versions": [],
                "reason": "The tenant database is a link."}
    files = list_migrations()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        newly = []
        for file in files:
            version = file.name
            if version in applied:
                continue
            sql = file.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            )
            newly.append(version)
        conn.commit()
        versions = sorted({row[0] for row in conn.execute("SELECT version FROM schema_migrations")})
        return {
            "ready": True,
            "backend": "sqlite",
            "path": str(db_path),
            "applied": newly,
            "versions": versions,
            "reason": "",
        }
    finally:
        conn.close()


def applied_versions(path: str | Path) -> list[str]:
    """Read applied migration versions without applying new ones."""
    db_path = Path(path)
    if sqlite_path_is_linked(db_path) or not db_path.is_file():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not rows:
            return []
        return sorted({row[0] for row in conn.execute("SELECT version FROM schema_migrations")})
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def apply_migrations(uri: str | None = None) -> dict:
    """Select backend from URI / env. Postgres stays explicitly unready for now."""
    raw = (uri if uri is not None else os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not raw or raw.startswith(("sqlite:", "file:", "local:")):
        path = _sqlite_path(raw) if raw else ROOT / "runs" / ".qpilot.sqlite"
        return apply_sqlite(path)
    if raw.startswith(("postgres://", "postgresql://")):
        try:
            from .postgres_drill import apply_migrations_psql
            result = apply_migrations_psql(dsn=raw)
        except Exception as exc:
            return {
                "ready": False,
                "backend": "postgres",
                "applied": [],
                "versions": [p.name for p in list_migrations()],
                "reason": f"Postgres apply failed: {exc}",
            }
        return {
            "ready": bool(result.get("ok")),
            "backend": "postgres",
            "applied": result.get("applied") or [],
            "versions": result.get("files") or [p.name for p in list_migrations()],
            "reason": "" if result.get("ok") else (result.get("reason") or "postgres migration failed"),
        }
    return {"ready": False, "backend": "unknown", "applied": [], "versions": [],
            "reason": "Unsupported database URI; use sqlite: or postgresql://"}


def migration_status(uri: str | None = None) -> dict:
    """Report migration files and applied versions without side effects."""
    files = [p.name for p in list_migrations()]
    raw = (uri if uri is not None else os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL") or "").strip()
    if raw.startswith(("postgres://", "postgresql://")):
        evidence = ROOT / "docs" / "ops-evidence" / "postgres_isolation_drill.json"
        live_ok = False
        from .finalization import folder_is_linked
        if evidence.is_file() and not folder_is_linked(evidence):
            try:
                import json
                live_ok = bool(json.loads(evidence.read_text(encoding="utf-8")).get("ok"))
            except (OSError, ValueError):
                live_ok = False
        return {
            "configured": bool(files),
            "ready": live_ok,
            "backend": "postgres",
            "versions": files,
            "applied": files if live_ok else [],
            "reason": (
                "Live Postgres isolation drill evidence present"
                if live_ok else
                "Postgres URL set; run isolation drill to establish readiness"
            ),
        }
    path = _sqlite_path(raw) if raw else ROOT / "runs" / ".qpilot.sqlite"
    applied = applied_versions(path)
    return {
        "configured": bool(files),
        "ready": bool(files) and set(files).issubset(set(applied)),
        "backend": "sqlite",
        "path": str(path),
        "versions": files,
        "applied": applied,
        "reason": ("all migration files applied on SQLite" if files and set(files).issubset(set(applied))
                   else "migration SQL present; call apply_migrations() to apply on SQLite"),
    }
