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


def list_audits(*, limit: int = 50, tenant_id: str | None = None,
                db_path: str | Path | None = None) -> list[dict]:
    """Newest audit events first. Optional tenant_id scopes the list (Gate G)."""
    path = Path(db_path) if db_path else DEFAULT_DB
    if not path.is_file():
        return []
    conn = _connect(path)
    try:
        lim = max(1, int(limit))
        tid = (tenant_id or "").strip()
        if tid:
            rows = conn.execute(
                "SELECT audit_id, tenant_id, actor, action, allowed, detail, created_at "
                "FROM audit_events WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?",
                (tid, lim),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT audit_id, tenant_id, actor, action, allowed, detail, created_at "
                "FROM audit_events ORDER BY created_at DESC LIMIT ?",
                (lim,),
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


def export_audits(*, limit: int = 200, tenant_id: str | None = None,
                  db_path: str | Path | None = None) -> dict:
    """Offline audit export package for Gate G evidence (Studio SSO still open)."""
    events = list_audits(limit=limit, tenant_id=tenant_id, db_path=db_path)
    return {
        "gate_g_complete": False,
        "export": "audit_events",
        "tenant_id": (tenant_id or "").strip() or None,
        "count": len(events),
        "events": events,
        "reason": "SQLite audit export available; Studio SSO / independent review still open",
    }
