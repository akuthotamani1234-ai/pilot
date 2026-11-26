"""Incremental, resumable, read-only Jira and Confluence synchronization into the requirements store.

Jira (sync_jira):

  first sync     every story of the scope (project + issue types + optional filter), oldest change first
  later syncs    only stories updated since the last complete sync (with an overlap for Jira's time zones;
                 unchanged content is recognized by its hash and makes no new version)
  resume         after a failure or a page limit, the next sync continues from the saved page token of the same
                 query; an expired page token starts that query again (nothing is lost, duplicates are ignored)
  partial        a story that cannot be read or normalized is listed in failed_items; the rest are stored; the
                 high-water mark does not move, so the next sync reads that window again
  missing        after a complete FULL sync, stories of the scope Jira no longer returns are marked missing (kept)
  audit          every sync, and every refused one, is recorded with backend/audit_store.py (no secrets)

Confluence (sync_confluence_space, follow_links, link_story):
  space sync     pages of a space, most recently changed first; later syncs stop at the first page older than the
                 last complete sync; Confluence's own version number is kept; resumable from the saved cursor
  linked pages   breadth-first from given pages up to `depth` link steps and `max_pages` pages; each page is read
                 once (circular links end there); a page that is gone or not permitted is listed as inaccessible
                 (and marked missing when it was stored before), and the rest go on
  story links    a stored Jira story -> the Confluence pages its remote links and description point to, and the
                 stored pages that mention it; each link records how it was found
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .. import audit_store
from . import confluence, jira, store
from .client import AtlassianError, Client
from .models import ISSUE_KEY, PAGE_ID, Connection, ImportFilter, Product, SourceKind, SyncStatus, parse_time

ACTION = "requirements.sync.jira"
CONFLUENCE_ACTION = "requirements.sync.confluence"
LINK_ACTION = "requirements.link"
CONFLUENCE_OVERLAP = timedelta(minutes=5)  # (Confluence times are exact UTC; this only covers clock skew)


def _audit(actor: str, allowed: bool, tenant_id: str, detail: dict, audit_db=None, action: str = ACTION) -> None:
    try:
        audit_store.record_audit(actor=actor or "system", action=action, allowed=allowed, tenant_id=tenant_id,
                                 detail=json.dumps(detail, sort_keys=True, default=str)[:2000], db_path=audit_db)
    except (OSError, ValueError):
        pass  # (an audit database problem never hides the sync result; the result says it)


def _check(connection: Connection, client: Client, tenant_id: str, product: Product, actor: str, audit_db,
           action: str) -> None:
    """The connection and its client belong to this tenant, and are of the expected product."""
    if (connection.tenant_id != tenant_id or client.connection.tenant_id != tenant_id
            or client.connection.id != connection.id):
        _audit(actor, False, tenant_id, {"connection": connection.id, "why": "connection of another tenant"},
               audit_db, action)
        raise PermissionError("this connection belongs to another tenant")
    if connection.product != product:
        raise ValueError(f"not a {product.value} connection")


def sync_jira(db, connection: Connection, client: Client, *, tenant_id: str, project: str,
              issue_types=None, extra: str = "", actor: str = "system", full: bool = False,
              page_size: int = jira.PAGE_SIZE, max_pages: int | None = None, audit_db=None,
              now: datetime | None = None, filters: ImportFilter | None = None,
              should_stop: Callable[[], bool] | None = None, progress: Callable[[dict], None] | None = None) -> dict:
    """filters: an ImportFilter (its project and types win; its other fields narrow the scope, which then has its
    own cursor). should_stop: checked after every stored page - a stop leaves a resumable cursor (status
    'cancelled'). progress: called with the running result after every page."""
    if filters is not None:
        project = filters.project
        issue_types = filters.types or issue_types
        extra = " AND ".join(x for x in (jira.filter_jql(filters), extra) if x)
    _check(connection, client, tenant_id, Product.jira, actor, audit_db, ACTION)
    issue_types = list(issue_types) if issue_types else list(connection.work_item_types)
    scope = "jql:" + jira.build_jql(project, issue_types, extra)
    cursor = store.load_cursor(db, tenant_id, connection.id, scope)
    started = now or datetime.now(UTC)
    result = {"scope": scope, "status": "", "new": 0, "changed": 0, "unchanged": 0, "reappeared": 0,
              "failed_items": [], "pages": 0, "missing": [], "resumed": False, "error": "",
              "work_item_types": issue_types, "warnings": [], "new_keys": [], "changed_keys": [], "mode":
              "full" if full else "incremental"}

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
        ac_field, target_fields = jira.special_fields(client)
        fields = jira.BASE_FIELDS + ([ac_field] if ac_field else []) + list(target_fields)
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
                    item = jira.normalize(issue, connection, ac_field=ac_field, target_fields=target_fields,
                                          retrieved_at=started)
                    outcome, _ = store.upsert_source(db, item["source"], item["story"], scope=scope)
                except (ValueError, TypeError, KeyError) as error:
                    failed.append(f"{key or '?'}: {str(error)[:120]}")
                    continue
                result[outcome] += 1
                if outcome in ("new", "changed", "reappeared"):
                    result["new_keys" if outcome == "new" else "changed_keys"].append(key)
                seen.add(item["source"].key)
                if key:
                    failed = [f for f in failed if not f.startswith(key + ":")]
            token = page["next_page_token"]
            cursor = cursor.model_copy(update={"next_page_token": "" if page["is_last"] else token,
                                               "fetched": cursor.fetched + len(page["issues"]),
                                               "failed_items": failed[:200]})
            store.save_cursor(db, cursor)  # (after each stored page: a failure resumes from here)
            if progress:
                progress(dict(result, failed_items=list(failed)))
            if page["is_last"] or not token:
                break
            if should_stop and should_stop():
                result.update(status="cancelled", failed_items=failed)
                _audit(actor, True, tenant_id, {"connection": connection.id, **_summary(result)}, audit_db)
                return result
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
    stored = sum(result[k] for k in ("new", "changed", "unchanged", "reappeared"))
    if full_scan and not result["resumed"] and stored == 0:
        result["warnings"].append(zero_result_warning(client, project, issue_types, extra))
    _audit(actor, True, tenant_id, {"connection": connection.id, **_summary(result)}, audit_db)
    return result


def zero_result_warning(client: Client, project: str, issue_types: list[str], extra: str = "") -> str:
    """Why an import found nothing: which work-item types the project really has, and how many of each."""
    asked = ", ".join(issue_types)
    text = f"0 work items imported from {project} (types: {asked}{'; filter: ' + extra if extra else ''})."
    try:
        counts = [c for c in jira.type_counts(client, project) if c["count"]]
    except (AtlassianError, ValueError) as error:
        return text + f" The project's work-item types could not be read ({str(error)[:120]})."
    if not counts:
        return text + f" {project} has no work items this account can see (or the project key is wrong)."
    found = ", ".join(f"{c['name']} ({c['count']})" for c in counts)
    return text + f" {project} has: {found}. Choose those types to import them."


def _summary(result: dict) -> dict:
    return {k: (len(v) if isinstance(v, list) else v) for k, v in result.items() if k != "scope"} | {
        "scope": result["scope"][:300]}


# ================================================================ Confluence

STOP_KINDS = {"auth_expired", "auth_missing", "rate_limited", "network", "server", "redirect"}  # (site-wide: stop)


def _store_page(db, connection: Connection, page: dict, tenant_id: str, scope: str, started: datetime,
                space_key: str = "") -> tuple[str, str, dict]:
    """Normalize and store one page; record its links to other pages and to STORED Jira stories it mentions.
    Returns (outcome, source key, content)."""
    item = confluence.normalize(page, connection, space_key=space_key, retrieved_at=started)
    outcome, stored = store.upsert_source(db, item["source"], item["content"], scope=scope, native_version=True)
    key = stored.key
    links = item["content"]["links"]
    for page_id in links["page_ids"]:
        if page_id != stored.source_id:
            store.save_link(db, tenant_id, key, f"{connection.id}:confluence_page:{page_id}", "links_to", "page body")
    for issue in links["issues"]:
        # (only real, synced stories: text such as 'UTF-8' looks like an issue key but is not one)
        for story_key in store.find_sources(db, tenant_id, SourceKind.jira_issue.value, issue):
            store.save_link(db, tenant_id, key, story_key, "mentions", "page body")
    return outcome, key, item["content"]


def sync_confluence_space(db, connection: Connection, client: Client, *, tenant_id: str, space_key: str,
                          actor: str = "system", full: bool = False, page_size: int = confluence.PAGE_SIZE,
                          max_pages: int | None = None, audit_db=None, now: datetime | None = None) -> dict:
    _check(connection, client, tenant_id, Product.confluence, actor, audit_db, CONFLUENCE_ACTION)
    scope = f"space:{space_key}"
    started = now or datetime.now(UTC)
    result = {"scope": scope, "status": "", "new": 0, "changed": 0, "unchanged": 0, "reappeared": 0,
              "failed_items": [], "pages": 0, "missing": [], "resumed": False, "error": "", "truncated": [],
              "new_keys": [], "changed_keys": [], "mode": "space"}

    def finish(cursor, status: SyncStatus, error: str = "", **update) -> dict:
        cursor = cursor.model_copy(update={"status": status, "last_error": error[:500], **update})
        store.save_cursor(db, cursor)
        result.update(status=status.value, error=cursor.last_error, failed_items=failed)
        _audit(actor, True, tenant_id, {"connection": connection.id, **_summary(result)}, audit_db, CONFLUENCE_ACTION)
        return result

    cursor = store.load_cursor(db, tenant_id, connection.id, scope)
    failed: list[str] = []
    try:
        found = confluence.spaces(client, [space_key])
    except AtlassianError as error:
        return finish(cursor, SyncStatus.failed, str(error))
    space = next((s for s in found if s["key"] == space_key), None)
    if not space:
        return finish(cursor, SyncStatus.failed, f"not_found: space {space_key} does not exist or is not visible")

    since = None if full else cursor.high_water
    query = f"space:{space['id']}|since=" + ("" if since is None else since.isoformat())
    resuming = bool(cursor.next_page_token and cursor.active_query and cursor.status != SyncStatus.complete
                    and not full)
    if resuming:
        query, token = cursor.active_query, cursor.next_page_token
        since_text = query.split("|since=", 1)[1] if "|since=" in query else ""
        since = datetime.fromisoformat(since_text) if since_text else None
        result["resumed"] = True
    else:
        token = ""
        cursor = cursor.model_copy(update={"active_query": query, "next_page_token": "", "started_at": started,
                                           "failed_items": [], "fetched": 0, "last_error": ""})
    failed = list(cursor.failed_items)
    cursor = cursor.model_copy(update={"status": SyncStatus.running})
    store.save_cursor(db, cursor)
    seen: set[str] = set()
    older_reached = False
    try:
        while True:
            listing = confluence.space_pages(client, space["id"], token, page_size)
            result["pages"] += 1
            for page in listing["pages"]:
                page_id = str(page.get("id", "")) if isinstance(page, dict) else ""
                try:
                    changed_at = (page.get("version") or {}).get("createdAt")
                    if since is not None and changed_at:
                        if parse_time(changed_at) < since - CONFLUENCE_OVERLAP:
                            older_reached = True  # (newest first: everything after this is older too)
                            break
                    outcome, key, content = _store_page(db, connection, page, tenant_id, scope, started, space_key)
                except (ValueError, TypeError, KeyError) as error:
                    failed.append(f"{page_id or '?'}: {str(error)[:120]}")
                    continue
                result[outcome] += 1
                if outcome in ("new", "changed", "reappeared"):
                    result["new_keys" if outcome == "new" else "changed_keys"].append(page_id)
                seen.add(key)
                if content["truncated"]:
                    result["truncated"].append(key)
                failed = [f for f in failed if not f.startswith(page_id + ":")]
            token = "" if older_reached else listing["cursor"]
            cursor = cursor.model_copy(update={"next_page_token": token, "fetched": cursor.fetched
                                               + len(listing["pages"]), "failed_items": failed[:200]})
            store.save_cursor(db, cursor)
            if not token:
                break
            if max_pages is not None and result["pages"] >= max_pages:
                return finish(cursor, SyncStatus.running)
    except AtlassianError as error:
        return finish(cursor, SyncStatus.failed, str(error), failed_items=failed[:200])

    if failed:
        return finish(cursor, SyncStatus.partial, next_page_token="", active_query="", failed_items=failed[:200])
    if since is None and not result["resumed"]:
        result["missing"] = store.mark_missing(db, tenant_id, connection.id, scope, seen)
    return finish(cursor, SyncStatus.complete, next_page_token="", active_query="",
                  high_water=cursor.started_at or started, failed_items=[])


def follow_links(db, connection: Connection, client: Client, *, tenant_id: str, page_ids: list[str],
                 depth: int = 1, max_pages: int = 50, from_key: str = "", relation: str = "specified_by",
                 found_via: str = "", actor: str = "system", audit_db=None, now: datetime | None = None) -> dict:
    """Read the given pages and the pages they link to, breadth-first, up to `depth` steps and `max_pages` pages.

    depth 0 = only the given pages. Each page is read once, so circular links end. A page Atlassian answers 'not
    found' / 'no permission' for is listed in `inaccessible` (and marked missing if it was stored); the others go
    on. A site-wide problem (expired token, rate limit after retries, network) stops the walk: `error`."""
    _check(connection, client, tenant_id, Product.confluence, actor, audit_db, LINK_ACTION)
    if depth < 0 or max_pages < 1:
        raise ValueError("depth >= 0 and max_pages >= 1")
    started = now or datetime.now(UTC)
    result = {"pages": [], "inaccessible": [], "failed_items": [], "limit_reached": False, "error": "",
              "new": 0, "changed": 0, "unchanged": 0, "reappeared": 0}
    queue = [(pid, 0, from_key) for pid in dict.fromkeys(page_ids) if PAGE_ID.match(str(pid))]
    visited: set[str] = set()
    space_ids: dict[str, str] = {}
    while queue:
        page_id, level, parent = queue.pop(0)
        if page_id in visited:
            if parent:
                store.save_link(db, tenant_id, parent, f"{connection.id}:confluence_page:{page_id}",
                                relation if parent == from_key else "links_to", found_via or "page body")
            continue
        if len(visited) >= max_pages:
            result["limit_reached"] = True
            break
        visited.add(page_id)
        key = f"{connection.id}:confluence_page:{page_id}"
        try:
            page = confluence.get_page(client, page_id)
            if str(page.get("status", "current")) not in ("current", "draft"):
                raise AtlassianError("not_found", f"page is {page.get('status')}")
            outcome, key, content = _store_page(db, connection, page, tenant_id, "", started)
        except AtlassianError as error:
            if error.kind in STOP_KINDS:
                result["error"] = str(error)
                break
            if error.kind in ("not_found", "forbidden"):  # (deleted, trashed, or no permission: no longer visible)
                result["inaccessible"].append({"page_id": page_id, "why": error.kind})
                store.mark_source_missing(db, tenant_id, key)
            else:  # (too large, unreadable answer: the page itself may be fine)
                result["failed_items"].append(f"{page_id}: {error.kind}")
            continue
        except (ValueError, TypeError, KeyError) as error:
            result["failed_items"].append(f"{page_id}: {str(error)[:120]}")
            continue
        result[outcome] += 1
        result["pages"].append(key)
        if parent:
            store.save_link(db, tenant_id, parent, key, relation if parent == from_key else "links_to",
                            found_via if parent == from_key else "page body")
        if level >= depth:
            continue
        children = list(content["links"]["page_ids"])
        for space, title in content["links"]["page_titles"]:
            try:
                sid = space_ids.get(space) if space else content["space_id"]
                if sid is None:
                    found = confluence.spaces(client, [space])
                    sid = space_ids[space] = found[0]["id"] if found else ""
                child = confluence.find_page(client, sid, title) if sid else ""
            except (AtlassianError, ValueError):
                child = ""
            if child:
                children.append(child)
            else:
                result["inaccessible"].append({"page_id": "", "title": title, "why": "not_found"})
        queue += [(c, level + 1, key) for c in dict.fromkeys(children) if c != page_id]
    _audit(actor, True, tenant_id, {"connection": connection.id, "from": from_key, "depth": depth,
                                    **_summary({**result, "scope": ""})}, audit_db, LINK_ACTION)
    return result


def confluence_pages_of_story(story: dict, remote: list[dict], host: str) -> list[tuple[str, str]]:
    """(page id, how it was found) for a stored story: its remote links, then links in its text."""
    out: dict[str, str] = {}
    for link in remote:
        gid = re.search(r"(?:^|&)pageId=(\d{1,20})(?:&|$)", link.get("global_id", ""))
        ids = [gid.group(1)] if gid else confluence.page_ids_in(link.get("url", ""), host)
        for pid in ids:
            out.setdefault(pid, "jira remote link")
    text = "\n".join([story.get("description", ""), story.get("acceptance_criteria", "")])
    for pid in confluence.page_ids_in(text, host):
        out.setdefault(pid, "jira description")
    return list(out.items())


def link_story(db, jira_connection: Connection, jira_client: Client, conf_connection: Connection,
               conf_client: Client, *, tenant_id: str, issue_key: str, depth: int = 1, max_pages: int = 25,
               actor: str = "system", audit_db=None, now: datetime | None = None) -> dict:
    """Connect a synced Jira story to its Confluence requirement pages (and the pages they link to)."""
    _check(jira_connection, jira_client, tenant_id, Product.jira, actor, audit_db, LINK_ACTION)
    _check(conf_connection, conf_client, tenant_id, Product.confluence, actor, audit_db, LINK_ACTION)
    story_key = f"{jira_connection.id}:jira_issue:{issue_key}"
    stored = store.get_source(db, tenant_id, story_key)
    if not stored:
        raise LookupError(f"{issue_key} is not synced yet: run the Jira sync first")
    notes = []
    try:
        remote = jira.remote_links(jira_client, issue_key)
    except AtlassianError as error:
        if error.kind in STOP_KINDS:
            raise
        remote, notes = [], [f"remote links not readable ({error.kind})"]
    found = confluence_pages_of_story(stored["content"], remote, conf_connection.host)
    # pages already stored that mention the story (found while syncing a space)
    for link in store.links_to(db, tenant_id, story_key):
        if link["relation"] == "mentions" and ":confluence_page:" in link["from_key"]:
            pid = link["from_key"].rsplit(":", 1)[1]
            if pid not in dict(found):
                found.append((pid, "page mentions the story"))
    result = {"story": story_key, "linked": [], "inaccessible": [], "failed_items": [], "limit_reached": False,
              "error": "", "notes": notes}
    for pid, how in found:
        walk = follow_links(db, conf_connection, conf_client, tenant_id=tenant_id, page_ids=[pid], depth=depth,
                            max_pages=max_pages, from_key=story_key, relation="specified_by", found_via=how,
                            actor=actor, audit_db=audit_db, now=now)
        result["linked"] += [k for k in walk["pages"] if k not in result["linked"]]
        result["inaccessible"] += walk["inaccessible"]
        result["failed_items"] += walk["failed_items"]
        result["limit_reached"] |= walk["limit_reached"]
        if walk["error"]:
            result["error"] = walk["error"]
            break
    return result


# ---------------------------------------------------------------- Milestone 2: targeted sync, preview, import runs

MAX_RELATED = 50
RELATED = ("subtasks", "parent", "linked")


def _fields(client: Client) -> tuple[str, list[str], dict[str, str]]:
    """(acceptance-criteria field, the fields to read, {target field id: name})"""
    ac_field, targets = jira.special_fields(client)
    return ac_field, jira.BASE_FIELDS + ([ac_field] if ac_field else []) + list(targets), targets


def sync_items(db, connection: Connection, client: Client, *, tenant_id: str, keys: list[str],
               include: tuple[str, ...] = (), actor: str = "system", audit_db=None, now: datetime | None = None,
               should_stop: Callable[[], bool] | None = None, progress: Callable[[dict], None] | None = None) -> dict:
    """Import exactly these work items (and, if asked, their sub-tasks, parent and linked work items, one step).

    A targeted import never touches a project's cursor and never marks other work items missing: an item it stores
    keeps the project scope it already had. A requested item Jira no longer shows is listed as inaccessible, and
    marked missing only if it was imported before (it is the item that was asked for)."""
    _check(connection, client, tenant_id, Product.jira, actor, audit_db, ACTION)
    unknown = set(include) - set(RELATED)
    if unknown:
        raise ValueError(f"include can only name {', '.join(RELATED)}")
    for k in keys:
        if not ISSUE_KEY.match(k):
            raise ValueError(f"not an issue key: {k!r}")
    started = now or datetime.now(UTC)
    scope = "items:" + ",".join(keys)[:1900]
    result = {"scope": scope, "status": "", "new": 0, "changed": 0, "unchanged": 0, "reappeared": 0,
              "failed_items": [], "pages": 0, "missing": [], "resumed": False, "error": "", "warnings": [],
              "new_keys": [], "changed_keys": [], "mode": "items", "requested": list(keys), "inaccessible": [],
              "related": [], "work_item_types": []}
    try:
        ac_field, fields, target_fields = _fields(client)
        queue = [(k, "") for k in keys]
        done: set[str] = set()
        while queue:
            key, relation_from = queue.pop(0)
            if key in done:
                continue
            done.add(key)
            try:
                issue = jira.get_issue(client, key, fields)
            except AtlassianError as error:
                if error.kind not in ("not_found", "forbidden"):
                    raise
                if not relation_from:
                    result["inaccessible"].append(f"{key}: {error.kind}")
                    if store.mark_source_missing(db, tenant_id, f"{connection.id}:jira_issue:{key}"):
                        result["missing"].append(key)
                continue
            result["pages"] += 1
            try:
                item = jira.normalize(issue, connection, ac_field=ac_field, target_fields=target_fields,
                                          retrieved_at=started)
                outcome, _ = store.upsert_source(db, item["source"], item["story"], scope="")
            except (ValueError, TypeError, KeyError) as error:
                result["failed_items"].append(f"{key}: {str(error)[:120]}")
                continue
            result[outcome] += 1
            if outcome in ("new", "changed", "reappeared"):
                result["new_keys" if outcome == "new" else "changed_keys"].append(key)
            story_key = item["source"].key
            if relation_from:
                result["related"].append(f"{key} ({relation_from})")
            else:  # (related work items of the REQUESTED ones only: one step, bounded)
                story = item["story"]
                more = []
                if "parent" in include and story["parent"]:
                    more.append((story["parent"], f"parent of {key}"))
                if "linked" in include:
                    more += [(x["key"], f"{x['type'] or 'linked'} {key}") for x in story["links"]]
                if "subtasks" in include:
                    page = jira.search(client, f"parent = {key} ORDER BY key ASC", ["summary"], "", MAX_RELATED)
                    more += [(str(i.get("key", "")), f"sub-task of {key}") for i in page["issues"]
                             if ISSUE_KEY.match(str(i.get("key", "")))]
                for other, why in more:
                    if len(done) + len(queue) >= len(keys) + MAX_RELATED:
                        result["warnings"].append(f"related work items capped at {MAX_RELATED}")
                        break
                    store.save_link(db, tenant_id, story_key, f"{connection.id}:jira_issue:{other}",
                                    "related", why[:120])
                    queue.append((other, why))
            if progress:
                progress(dict(result))
            if should_stop and should_stop():
                result["status"] = "cancelled"
                break
    except AtlassianError as error:
        result.update(status="failed", error=str(error)[:500])
    if not result["status"]:
        result["status"] = "partial" if result["failed_items"] or result["inaccessible"] else "complete"
    _audit(actor, True, tenant_id, {"connection": connection.id, **_summary(result)}, audit_db)
    return result


def preview(db, connection: Connection, client: Client, *, tenant_id: str, filters: ImportFilter | None = None,
            keys: list[str] | None = None, limit: int = 50, next_page_token: str = "", actor: str = "system",
            audit_db=None) -> dict:
    """What an import would read, before anything is stored: keys, summaries, types, statuses and, for each, whether
    it is new, updated or unchanged against what is already imported. Nothing is written to the store."""
    _check(connection, client, tenant_id, Product.jira, actor, audit_db, "requirements.preview")
    limit = max(1, min(100, int(limit)))
    ac_field, fields, target_fields = _fields(client)
    issues, token, total, query = [], "", None, ""
    inaccessible = []
    if keys:
        for key in keys[:limit]:
            try:
                issues.append(jira.get_issue(client, key, fields))
            except AtlassianError as error:
                if error.kind not in ("not_found", "forbidden"):
                    raise
                inaccessible.append(f"{key}: {error.kind}")
        total = len(issues)
    else:
        if filters is None:
            raise ValueError("a preview needs filters (a project) or work-item keys")
        types = filters.types or connection.work_item_types
        query = jira.build_jql(filters.project, types, jira.filter_jql(filters))
        page = jira.search(client, query, fields, next_page_token, limit)
        issues, token = page["issues"], ("" if page["is_last"] else page["next_page_token"])
        try:
            total = jira.count(client, query.split(" ORDER BY ")[0])
        except AtlassianError:
            total = None  # (no estimate available: the list is still exact)
    items = []
    for issue in issues:
        key = str(issue.get("key", "")) if isinstance(issue, dict) else ""
        try:
            n = jira.normalize(issue, connection, ac_field=ac_field, target_fields=target_fields)
        except (ValueError, TypeError, KeyError) as error:
            items.append({"key": key or "?", "state": "unreadable", "error": str(error)[:120]})
            continue
        stored = store.get_source(db, tenant_id, n["source"].key)
        if not stored:
            state = "new"
        elif stored["source"].content_hash != n["source"].content_hash:
            state = "updated"
        else:
            state = "unchanged" if stored["present"] else "reappeared"
        s = n["story"]
        items.append({"key": key, "summary": s["summary"], "type": s["type"], "status": s["status"],
                      "priority": s["priority"], "updated": n["source"].updated.isoformat(), "state": state,
                      "stored_version": stored["source"].version if stored else None})
    counts = {st: sum(1 for i in items if i["state"] == st) for st in ("new", "updated", "unchanged", "reappeared")}
    return {"jql": query, "estimated_total": total, "items": items, "counts": counts, "inaccessible": inaccessible,
            "next_page_token": token}


def affected_requirements(db, tenant_id: str, source_keys: list[str]) -> list[dict]:
    """Requirements whose stored analysis no longer matches these changed sources (to re-analyse / re-review)."""
    from . import analysis as an
    out, seen = [], set()
    for analysis in store.list_analyses(db, tenant_id):
        if not set(analysis.source_versions) & set(source_keys):
            continue
        reasons = an.stale(db, tenant_id, analysis)
        if reasons and analysis.requirement.id not in seen:
            seen.add(analysis.requirement.id)
            out.append({"requirement": analysis.requirement.id, "reasons": reasons})
    return out


def run_import(db, connection: Connection, client: Client, *, tenant_id: str, mode: str,
               filters: ImportFilter | None = None, keys: list[str] | None = None, include: tuple[str, ...] = (),
               space_key: str = "", full_space: bool = False, actor: str = "system", audit_db=None,
               should_stop: Callable[[], bool] | None = None, progress: Callable[[dict], None] | None = None) -> dict:
    """One import as people see it: incremental | full | items (Jira) or space (Confluence). Adds what was found
    (criteria per new / updated work item), which analysed requirements are now out of date, how long it took and
    the last successful sync, and keeps the run in the sync history. It never runs tests."""
    from . import analysis as an
    clock = time.monotonic()
    started = datetime.now(UTC)
    if mode in ("incremental", "full"):
        if filters is None:
            raise ValueError("a project import needs filters with a project")
        result = sync_jira(db, connection, client, tenant_id=tenant_id, project=filters.project, filters=filters,
                           actor=actor, full=mode == "full", audit_db=audit_db, should_stop=should_stop,
                           progress=progress)
    elif mode == "items":
        if not keys:
            raise ValueError("an items import needs work-item keys")
        result = sync_items(db, connection, client, tenant_id=tenant_id, keys=keys, include=include, actor=actor,
                            audit_db=audit_db, should_stop=should_stop, progress=progress)
    elif mode == "space":
        result = sync_confluence_space(db, connection, client, tenant_id=tenant_id, space_key=space_key, actor=actor,
                                       audit_db=audit_db, full=full_space)
    else:
        raise ValueError("mode is incremental, full, items or space")
    kind = "confluence_page" if mode == "space" else "jira_issue"
    touched = [f"{connection.id}:{kind}:{k}" for k in result.get("new_keys", []) + result.get("changed_keys", [])]
    criteria, needs_review = {}, []
    for source_key in touched:
        try:
            req = an.build_requirement(db, tenant_id, source_key)
        except (LookupError, ValueError):
            continue
        criteria[req.id] = len(req.criteria)
        if store.get_analysis(db, tenant_id, req.id) is None or req.id in {
                a["requirement"] for a in affected_requirements(db, tenant_id, [source_key])}:
            needs_review.append(req.id)
    finished = datetime.now(UTC)
    result.update(mode=mode, started_at=started.isoformat(), finished_at=finished.isoformat(),
                  duration_s=round(time.monotonic() - clock, 2), criteria_extracted=criteria,
                  needs_analysis=needs_review, affected=affected_requirements(db, tenant_id, touched))
    store.record_sync_run(db, tenant_id, connection.id, mode, result, actor)
    result["last_success"] = store.last_success(db, tenant_id, connection.id)
    return result
