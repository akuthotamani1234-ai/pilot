"""Incremental, resumable, read-only Jira synchronization into the requirements store.

  first sync     every story of the scope (project + issue types + optional filter), oldest change first
  later syncs    only stories updated since the last complete sync (with an overlap for Jira's time zones;
                 unchanged content is recognized by its hash and makes no new version)
  resume         after a failure or a page limit, the next sync continues from the saved page token of the same
                 query; an expired page token starts that query again (nothing is lost, duplicates are ignored)
  partial        a story that cannot be read or normalized is listed in failed_items; the rest are stored; the
                 high-water mark does not move, so the next sync reads that window again
  missing        after a complete FULL sync, stories of the scope Jira no longer returns are marked missing (kept)
  audit          every sync, and every refused one, is recorded with backend/audit_store.py (no secrets)
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from .. import audit_store
from . import jira, store
from .client import AtlassianError, Client
from .models import Connection, Product, SyncStatus

ACTION = "requirements.sync.jira"


def _audit(actor: str, allowed: bool, tenant_id: str, detail: dict, audit_db=None) -> None:
    try:
        audit_store.record_audit(actor=actor or "system", action=ACTION, allowed=allowed, tenant_id=tenant_id,
                                 detail=json.dumps(detail, sort_keys=True, default=str)[:2000], db_path=audit_db)
    except (OSError, ValueError):
        pass  # (an audit database problem never hides the sync result; the result says it)


def sync_jira(db, connection: Connection, client: Client, *, tenant_id: str, project: str,
              issue_types=jira.STORY_TYPES, extra: str = "", actor: str = "system", full: bool = False,
              page_size: int = jira.PAGE_SIZE, max_pages: int | None = None, audit_db=None,
              now: datetime | None = None) -> dict:
    if (connection.tenant_id != tenant_id or client.connection.tenant_id != tenant_id
            or client.connection.id != connection.id):
        _audit(actor, False, tenant_id, {"connection": connection.id, "why": "connection of another tenant"},
               audit_db)
        raise PermissionError("this connection belongs to another tenant")
    if connection.product != Product.jira:
        raise ValueError("not a Jira connection")
    scope = "jql:" + jira.build_jql(project, issue_types, extra)
    cursor = store.load_cursor(db, tenant_id, connection.id, scope)
    started = now or datetime.now(UTC)
    result = {"scope": scope, "status": "", "new": 0, "changed": 0, "unchanged": 0, "reappeared": 0,
              "failed_items": [], "pages": 0, "missing": [], "resumed": False, "error": ""}

    resuming = bool(cursor.next_page_token and cursor.active_query and cursor.status != SyncStatus.complete
                    and not full)
    if resuming:
        query, token = cursor.active_query, cursor.next_page_token
        result["resumed"] = True
    else:
        since = None if full else cursor.high_water
        query, token = jira.build_jql(project, issue_types, extra, since=since), ""
        cursor = cursor.model_copy(update={"active_query": query, "next_page_token": "", "started_at": started,
                                           "failed_items": [], "fetched": 0, "last_error": ""})
    full_scan = "updated >=" not in query
    cursor = cursor.model_copy(update={"status": SyncStatus.running})
    store.save_cursor(db, cursor)

    seen: set[str] = set()
    failed = list(cursor.failed_items)
    restarted = False
    try:
        ac_field = jira.acceptance_field(client)
        fields = jira.BASE_FIELDS + ([ac_field] if ac_field else [])
        while True:
            try:
                page = jira.search(client, query, fields, token, page_size)
            except AtlassianError as error:
                if error.kind == "bad_request" and token and not restarted:
                    token, restarted = "", True  # (an expired page token: read the same query again from the start)
                    continue
                raise
            result["pages"] += 1
            for issue in page["issues"]:
                key = str(issue.get("key", "")) if isinstance(issue, dict) else ""
                try:
                    item = jira.normalize(issue, connection, ac_field=ac_field, retrieved_at=started)
                    outcome, _ = store.upsert_source(db, item["source"], item["story"], scope=scope)
                except (ValueError, TypeError, KeyError) as error:
                    failed.append(f"{key or '?'}: {str(error)[:120]}")
                    continue
                result[outcome] += 1
                seen.add(item["source"].key)
                if key:
                    failed = [f for f in failed if not f.startswith(key + ":")]
            token = page["next_page_token"]
            cursor = cursor.model_copy(update={"next_page_token": "" if page["is_last"] else token,
                                               "fetched": cursor.fetched + len(page["issues"]),
                                               "failed_items": failed[:200]})
            store.save_cursor(db, cursor)  # (after each stored page: a failure resumes from here)
            if page["is_last"] or not token:
                break
            if max_pages is not None and result["pages"] >= max_pages:
                result["status"] = SyncStatus.running.value
                result["failed_items"] = failed
                _audit(actor, True, tenant_id, {"connection": connection.id, **_summary(result)}, audit_db)
                return result
    except AtlassianError as error:
        cursor = cursor.model_copy(update={"status": SyncStatus.failed, "last_error": str(error)[:500],
                                           "failed_items": failed[:200]})
        store.save_cursor(db, cursor)
        result.update(status="failed", error=cursor.last_error, failed_items=failed)
        _audit(actor, True, tenant_id, {"connection": connection.id, **_summary(result)}, audit_db)
        return result

    if failed:
        cursor = cursor.model_copy(update={"status": SyncStatus.partial, "next_page_token": "", "active_query": "",
                                           "failed_items": failed[:200]})
    else:
        if full_scan and not result["resumed"] and not restarted:
            result["missing"] = store.mark_missing(db, tenant_id, connection.id, scope, seen)
        cursor = cursor.model_copy(update={"status": SyncStatus.complete, "next_page_token": "",
                                           "active_query": "", "high_water": cursor.started_at or started,
                                           "failed_items": []})
    store.save_cursor(db, cursor)
    result.update(status=cursor.status.value, failed_items=failed)
    _audit(actor, True, tenant_id, {"connection": connection.id, **_summary(result)}, audit_db)
    return result


def _summary(result: dict) -> dict:
    return {k: (len(v) if isinstance(v, list) else v) for k, v in result.items() if k != "scope"} | {
        "scope": result["scope"][:300]}
