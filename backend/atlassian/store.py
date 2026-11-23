"""Requirements Intelligence storage: one SQLite file, every row tagged with its tenant.

  connections       Connection models (the token is never in them: only the secret's name)
  sources           the newest version of each Jira issue / Confluence page, with its normalized content
  source_versions   every version ever seen: content hash, Jira 'updated', normalized content (traceability needs
                    to know what a test was designed from)
  sync_cursors      where each sync stands (resume after a failure)
  links             story <-> page and page -> page links, with how each was found

Every function takes the tenant and filters by it: one tenant can never read or change another tenant's rows.
Same pattern as backend/approvals.py (a linked database file is refused).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..migrate import sqlite_path_is_linked
from .models import Connection, SourceRef, SyncCursor

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "runs" / ".requirements.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id));
CREATE TABLE IF NOT EXISTS sources (
    tenant_id TEXT NOT NULL, source_key TEXT NOT NULL, connection_id TEXT NOT NULL, kind TEXT NOT NULL,
    source_id TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL, updated TEXT NOT NULL,
    url TEXT NOT NULL, title TEXT NOT NULL, scope TEXT NOT NULL DEFAULT '', present INTEGER NOT NULL DEFAULT 1,
    retrieved_at TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, source_key));
CREATE TABLE IF NOT EXISTS source_versions (
    tenant_id TEXT NOT NULL, source_key TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL,
    updated TEXT NOT NULL, retrieved_at TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, source_key, version));
CREATE TABLE IF NOT EXISTS sync_cursors (
    tenant_id TEXT NOT NULL, connection_id TEXT NOT NULL, scope TEXT NOT NULL, data TEXT NOT NULL,
    PRIMARY KEY (tenant_id, connection_id, scope));
CREATE TABLE IF NOT EXISTS links (
    tenant_id TEXT NOT NULL, from_key TEXT NOT NULL, to_key TEXT NOT NULL, relation TEXT NOT NULL,
    found_via TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    PRIMARY KEY (tenant_id, from_key, to_key, relation));
CREATE INDEX IF NOT EXISTS sources_by_connection ON sources (tenant_id, connection_id, scope);
"""


def _tenant(tenant_id: str) -> str:
    tenant_id = (tenant_id or "").strip()
    if not tenant_id:
        raise ValueError("a tenant is required")
    return tenant_id


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db = Path(path) if path else DEFAULT_DB
    if sqlite_path_is_linked(db):
        raise ValueError("The requirements database is a link.")
    db.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_path_is_linked(db):
        raise ValueError("The requirements database is a link.")
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------- connections

def save_connection(db: sqlite3.Connection, connection: Connection) -> None:
    with db:
        db.execute("INSERT INTO connections (tenant_id, id, data, updated_at) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT (tenant_id, id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                   (connection.tenant_id, connection.id, connection.model_dump_json(), _now()))


def get_connection(db: sqlite3.Connection, tenant_id: str, connection_id: str) -> Connection | None:
    row = db.execute("SELECT data FROM connections WHERE tenant_id = ? AND id = ?",
                     (_tenant(tenant_id), connection_id)).fetchone()
    return Connection.model_validate_json(row["data"]) if row else None


def list_connections(db: sqlite3.Connection, tenant_id: str) -> list[Connection]:
    rows = db.execute("SELECT data FROM connections WHERE tenant_id = ? ORDER BY id", (_tenant(tenant_id),))
    return [Connection.model_validate_json(r["data"]) for r in rows]


# ---------------------------------------------------------------- sources

def upsert_source(db: sqlite3.Connection, source: SourceRef, data: dict, scope: str = "",
                  native_version: bool = False) -> tuple[str, SourceRef]:
    """Store one source read from Atlassian. Returns ('new' | 'changed' | 'unchanged' | 'reappeared', stored ref).

    Unchanged content (same hash) keeps its version; changed content gets a new version and the old one stays in
    source_versions. Jira has no content version number, so the store counts (native_version=False). Confluence
    numbers its versions itself (native_version=True): that number is kept, so a trace link names the exact
    Confluence version a test was designed from."""
    tenant = _tenant(source.tenant_id)
    row = db.execute("SELECT version, content_hash, present FROM sources WHERE tenant_id = ? AND source_key = ?",
                     (tenant, source.key)).fetchone()
    if row and row["content_hash"] == source.content_hash:
        with db:
            db.execute("UPDATE sources SET retrieved_at = ?, present = 1, scope = CASE WHEN ? = '' THEN scope "
                       "ELSE ? END WHERE tenant_id = ? AND source_key = ?",
                       (source.retrieved_at.isoformat(), scope, scope, tenant, source.key))
        stored = source.model_copy(update={"version": row["version"]})
        return ("unchanged" if row["present"] else "reappeared"), stored
    if native_version:
        version = source.version
        if row and version < row["version"]:
            raise ValueError(f"{source.key}: version {version} is older than the stored version {row['version']}")
    else:
        version = (row["version"] + 1) if row else 1
    stored = source.model_copy(update={"version": version})
    body = json.dumps({"source": json.loads(stored.model_dump_json()), "content": data}, sort_keys=True)
    with db:
        db.execute("INSERT OR REPLACE INTO source_versions (tenant_id, source_key, version, content_hash, updated, "
                   "retrieved_at, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (tenant, source.key, version, source.content_hash, source.updated.isoformat(),
                    source.retrieved_at.isoformat(), body))
        db.execute("INSERT INTO sources (tenant_id, source_key, connection_id, kind, source_id, version, "
                   "content_hash, updated, url, title, scope, present, retrieved_at, data) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?) ON CONFLICT (tenant_id, source_key) DO UPDATE SET "
                   "version = excluded.version, content_hash = excluded.content_hash, updated = excluded.updated, "
                   "url = excluded.url, title = excluded.title, present = 1, retrieved_at = excluded.retrieved_at, "
                   "data = excluded.data, scope = CASE WHEN excluded.scope = '' THEN sources.scope "
                   "ELSE excluded.scope END",
                   (tenant, source.key, source.connection_id, source.kind.value, source.source_id, version,
                    source.content_hash, source.updated.isoformat(), source.url, source.title, scope,
                    source.retrieved_at.isoformat(), body))
    return ("changed" if row else "new"), stored


def _row(row) -> dict:
    data = json.loads(row["data"])
    return {"source": SourceRef.model_validate(data["source"]), "content": data["content"],
            "present": bool(row["present"]) if "present" in row.keys() else True}


def get_source(db: sqlite3.Connection, tenant_id: str, source_key: str) -> dict | None:
    row = db.execute("SELECT data, present FROM sources WHERE tenant_id = ? AND source_key = ?",
                     (_tenant(tenant_id), source_key)).fetchone()
    return _row(row) if row else None


def list_sources(db: sqlite3.Connection, tenant_id: str, connection_id: str = "", include_missing: bool = False
                 ) -> list[dict]:
    q = "SELECT data, present FROM sources WHERE tenant_id = ?"
    args: list = [_tenant(tenant_id)]
    if connection_id:
        q += " AND connection_id = ?"
        args.append(connection_id)
    if not include_missing:
        q += " AND present = 1"
    return [_row(r) for r in db.execute(q + " ORDER BY source_key", args)]


def find_sources(db: sqlite3.Connection, tenant_id: str, kind: str, source_id: str) -> list[str]:
    """The source keys of an issue key / page id in this tenant (one per connection that has it)."""
    rows = db.execute("SELECT source_key FROM sources WHERE tenant_id = ? AND kind = ? AND source_id = ? "
                      "ORDER BY source_key", (_tenant(tenant_id), kind, source_id))
    return [r["source_key"] for r in rows]


def history(db: sqlite3.Connection, tenant_id: str, source_key: str) -> list[dict]:
    rows = db.execute("SELECT data FROM source_versions WHERE tenant_id = ? AND source_key = ? ORDER BY version",
                      (_tenant(tenant_id), source_key))
    return [_row(r) for r in rows]


def mark_missing(db: sqlite3.Connection, tenant_id: str, connection_id: str, scope: str, seen: set[str]) -> list[str]:
    """After a COMPLETE full sync of a scope: sources of that scope it did not return are no longer visible
    (deleted, moved, or no permission). They are kept, marked missing, never dropped from traceability."""
    rows = db.execute("SELECT source_key FROM sources WHERE tenant_id = ? AND connection_id = ? AND scope = ? "
                      "AND present = 1", (_tenant(tenant_id), connection_id, scope)).fetchall()
    gone = [r["source_key"] for r in rows if r["source_key"] not in seen]
    with db:
        db.executemany("UPDATE sources SET present = 0 WHERE tenant_id = ? AND source_key = ?",
                       [(tenant_id, k) for k in gone])
    return gone


def mark_source_missing(db: sqlite3.Connection, tenant_id: str, source_key: str) -> bool:
    """One source Atlassian now answers 'not found' / 'no permission' for: kept, marked missing."""
    with db:
        cur = db.execute("UPDATE sources SET present = 0 WHERE tenant_id = ? AND source_key = ? AND present = 1",
                         (_tenant(tenant_id), source_key))
    return cur.rowcount > 0


# ---------------------------------------------------------------- links

def save_link(db: sqlite3.Connection, tenant_id: str, from_key: str, to_key: str, relation: str, found_via: str
              ) -> None:
    now = _now()
    with db:
        db.execute("INSERT INTO links (tenant_id, from_key, to_key, relation, found_via, first_seen, last_seen) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (tenant_id, from_key, to_key, relation) DO UPDATE SET "
                   "last_seen = excluded.last_seen, found_via = excluded.found_via",
                   (_tenant(tenant_id), from_key, to_key, relation, found_via, now, now))


def links_from(db: sqlite3.Connection, tenant_id: str, from_key: str) -> list[dict]:
    rows = db.execute("SELECT to_key, relation, found_via FROM links WHERE tenant_id = ? AND from_key = ? "
                      "ORDER BY to_key, relation", (_tenant(tenant_id), from_key))
    return [dict(r) for r in rows]


def links_to(db: sqlite3.Connection, tenant_id: str, to_key: str) -> list[dict]:
    rows = db.execute("SELECT from_key, relation, found_via FROM links WHERE tenant_id = ? AND to_key = ? "
                      "ORDER BY from_key, relation", (_tenant(tenant_id), to_key))
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- cursors

def load_cursor(db: sqlite3.Connection, tenant_id: str, connection_id: str, scope: str) -> SyncCursor:
    row = db.execute("SELECT data FROM sync_cursors WHERE tenant_id = ? AND connection_id = ? AND scope = ?",
                     (_tenant(tenant_id), connection_id, scope)).fetchone()
    if row:
        return SyncCursor.model_validate_json(row["data"])
    return SyncCursor(tenant_id=tenant_id, connection_id=connection_id, scope=scope)


def save_cursor(db: sqlite3.Connection, cursor: SyncCursor) -> None:
    with db:
        db.execute("INSERT INTO sync_cursors (tenant_id, connection_id, scope, data) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT (tenant_id, connection_id, scope) DO UPDATE SET data = excluded.data",
                   (_tenant(cursor.tenant_id), cursor.connection_id, cursor.scope, cursor.model_dump_json()))
