"""Persist RBAC audit events into the Gate G SQLite schema."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .migrate import apply_migrations
from .rbac import audit_event

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "runs" / ".qpilot.sqlite"


def _connect(path: Path) -> sqlite3.Connection:
    apply_migrations(f"sqlite:{path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def record_audit(*, actor: str, action: str, allowed: bool, tenant_id: str = "", detail: str = "",
                 db_path: str | Path | None = None) -> dict:
    """Create and persist one audit event. Returns the event dict."""
    event = audit_event(actor=actor, action=action, allowed=allowed, tenant_id=tenant_id, detail=detail)
    path = Path(db_path) if db_path else DEFAULT_DB
    conn = _connect(path)
    try:
        conn.execute(
            "INSERT INTO audit_events(audit_id, tenant_id, actor, action, allowed, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event["audit_id"],
                event.get("tenant_id"),
                event["actor"],
                event["action"],
                1 if event["allowed"] else 0,
                event.get("detail") or "",
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    event["persisted"] = True
    event["db"] = str(path)
    return event


def list_audits(*, limit: int = 50, db_path: str | Path | None = None) -> list[dict]:
    """Newest audit events first."""
    path = Path(db_path) if db_path else DEFAULT_DB
    if not path.is_file():
        return []
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT audit_id, tenant_id, actor, action, allowed, detail, created_at "
            "FROM audit_events ORDER BY created_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [
            {
                "audit_id": row["audit_id"],
                "tenant_id": row["tenant_id"],
                "actor": row["actor"],
                "action": row["action"],
                "allowed": bool(row["allowed"]),
                "detail": row["detail"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()
