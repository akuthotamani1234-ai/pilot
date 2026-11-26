"""Read Jira Cloud: projects, the acceptance-criteria field, stories by JQL (paged), and one normalized story.

All calls are reads through client.Client. Jira Cloud's current search is POST /rest/api/3/search/jql, paged with
nextPageToken (the older /rest/api/3/search with startAt is being retired). Descriptions arrive in Atlassian
Document Format (ADF); adf_to_text keeps the words, headings, list items and line breaks.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from .client import AtlassianError, Client
from .models import (
    ISSUE_KEY,
    WORK_ITEM_TYPE,
    Connection,
    ImportFilter,
    SourceKind,
    SourceRef,
    content_hash,
    parse_time,
)

PAGE_SIZE = 50
STORY_TYPES = ("Story",)
BASE_FIELDS = ["summary", "description", "issuetype", "status", "labels", "priority", "updated", "created",
               "issuelinks", "parent", "project"]
# the custom field that holds acceptance criteria: 'Acceptance Criteria', 'AcceptanceCriteria', 'Acceptance_Criteria',
# 'Acceptance criterion', 'AC', 'ACs', 'Definition of Done'
AC_FIELD_NAME = re.compile(r"\bacceptance[\s_-]*criteri(a|on)s?\b|^\s*(acs?|definition of done|dod)\s*$", re.I)
EXACT_AC_FIELD = re.compile(r"^\s*acceptance[\s_-]*criteria\s*$", re.I)
MAX_TYPES = 20# JQL compares dates in the Jira user's own time zone and to the minute; an overlap of 14 h + 1 min covers every
# time zone. Re-read issues are recognized by their content hash and create no new version.
OVERLAP = timedelta(hours=14, minutes=1)
PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")


# ---------------------------------------------------------------- JQL

def jql_string(value: str) -> str:
    """A JQL string literal: quotes and backslashes escaped, no line breaks."""
    value = re.sub(r"[\r\n]+", " ", value or "")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def balanced(jql: str) -> bool:
    """Brackets balance and quotes close, outside quoted strings: an extra filter put in (...) cannot step out of
    them (e.g. 'x) OR (project = OTHER') and widen the import beyond its project."""
    depth, quote, escaped = 0, "", False
    for ch in jql or "":
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quote


def build_jql(project: str, issue_types=STORY_TYPES, extra: str = "", since: datetime | None = None,
              order: bool = True) -> str:
    """project = KEY AND issuetype in ("Story") [AND (extra)] [AND updated >= "..."] ORDER BY updated ASC, key ASC

    ORDER BY updated ascending lets the sync move its high-water mark forward page by page."""
    if not PROJECT_KEY.match(project or ""):
        raise ValueError("project must be a Jira project key such as SHOP")
    parts = [f"project = {project}"]
    issue_types = list(issue_types or [])
    if len(issue_types) > MAX_TYPES or any(not WORK_ITEM_TYPE.match(str(x)) for x in issue_types):
        raise ValueError("work-item types must be 1-20 plain type names such as Story or Task")
    if issue_types:
        parts.append("issuetype in (" + ", ".join(jql_string(t) for t in issue_types) + ")")
    if extra:
        if re.search(r"\border\s+by\b", extra, re.I):
            raise ValueError("the extra filter cannot contain ORDER BY")
        if not balanced(extra):
            raise ValueError("the extra filter has unbalanced brackets or quotes")
        parts.append(f"({extra})")
    if since is not None:
        start = (since.astimezone(UTC) - OVERLAP).strftime("%Y/%m/%d %H:%M")
        parts.append(f'updated >= "{start}"')
    return " AND ".join(parts) + (" ORDER BY updated ASC, key ASC" if order else "")


def filter_jql(f: ImportFilter) -> str:
    """The narrowing part of an import's JQL (everything but project and types); every value quoted."""
    def names(values):
        return ", ".join(jql_string(v) for v in values)

    def next_day(d: str) -> str:
        return (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y/%m/%d")

    parts = []
    if f.epic:
        parts.append(f"parent = {f.epic}")
    if f.sprint == "open":
        parts.append("sprint in openSprints()")
    elif f.sprint.isdigit():
        parts.append(f"sprint = {int(f.sprint)}")
    elif f.sprint:
        parts.append(f"sprint = {jql_string(f.sprint)}")
    if f.statuses:
        parts.append(f"status in ({names(f.statuses)})")
    if f.priorities:
        parts.append(f"priority in ({names(f.priorities)})")
    if f.assignee == "me":
        parts.append("assignee = currentUser()")
    elif f.assignee == "unassigned":
        parts.append("assignee is EMPTY")
    elif f.assignee:
        parts.append(f"assignee = {jql_string(f.assignee)}")
    if f.labels:
        parts.append(f"labels in ({names(f.labels)})")
    for field, start, end in (("created", f.created_from, f.created_to), ("updated", f.updated_from, f.updated_to)):
        if start:
            parts.append(f'{field} >= "{start.replace("-", "/")}"')
        if end:
            parts.append(f'{field} < "{next_day(end)}"')
    if f.text:
        parts.append(f"summary ~ {jql_string(f.text)}")
    if f.jql:
        if not balanced(f.jql):
            raise ValueError("the JQL filter has unbalanced brackets or quotes")
        parts.append(f"({f.jql})")
    return " AND ".join(parts)


MAX_KEYS = 200
_URL_KEY = re.compile(r"(?:/browse/|[?&]selectedIssue=|/issues/)([A-Z][A-Z0-9_]{0,19}-[1-9][0-9]{0,9})\b")


def parse_issue_refs(text: str, host: str) -> list[str]:
    """Issue keys from what a person typed: 'QPL-2', 'QPL-2, QPL-5', or work-item links of THIS site
    (https://<site>/browse/QPL-2, board links with ?selectedIssue=QPL-2, /issues/QPL-2). A link to another site is
    refused, so a targeted import stays on its connection."""
    from urllib.parse import unquote, urlparse
    keys: list[str] = []
    for token in re.split(r"[\s,;]+", (text or "").strip()):
        if not token:
            continue
        if token.lower().startswith(("http://", "https://")):
            url = urlparse(token)
            if url.scheme != "https" or (url.hostname or "").lower() != host.lower():
                raise ValueError(f"{token[:80]} is not a link to {host}")
            found = _URL_KEY.findall(unquote(url.path + ("?" + url.query if url.query else "")))
            if not found:
                raise ValueError(f"no work-item key in {token[:80]}")
            key = found[-1]
        else:
            key = token.upper()
            if not ISSUE_KEY.match(key):
                raise ValueError(f"{token[:40]!r} is not an issue key such as QPL-2")
        if key not in keys:
            keys.append(key)
    if len(keys) > MAX_KEYS:
        raise ValueError(f"at most {MAX_KEYS} work items at once")
    return keys


def keys_jql(keys: list[str]) -> str:
    for k in keys:
        if not ISSUE_KEY.match(k):
            raise ValueError(f"not an issue key: {k!r}")
    return f"key in ({', '.join(keys)}) ORDER BY key ASC"


def validate_jql(client: Client, jql: str) -> list[str]:
    """Jira's own check of a query (read-only POST /rest/api/3/jql/parse): [] when valid, else its messages."""
    data = client.post_read("/rest/api/3/jql/parse", {"queries": [jql]}, params={"validation": "strict"})
    queries = data.get("queries") or []
    if not queries or not isinstance(queries[0], dict):
        raise AtlassianError("invalid_response", "the JQL check gave no answer")
    return [str(e)[:300] for e in queries[0].get("errors") or []]


# ---------------------------------------------------------------- reads

def projects(client: Client) -> list[dict]:
    out, start = [], 0
    while True:
        page = client.get("/rest/api/3/project/search", {"startAt": start, "maxResults": PAGE_SIZE})
        values = page.get("values") or []
        out += [{"id": str(p.get("id", "")), "key": p.get("key", ""), "name": p.get("name", "")} for p in values
                if isinstance(p, dict) and PROJECT_KEY.match(str(p.get("key", "")))]
        if page.get("isLast", True) or not values:
            return out
        start += len(values)


# custom fields that name the application under test ('Environment', 'Test URL', 'Application', 'APK', 'App package',
# 'Bundle ID', 'API endpoint', 'Base URL', 'Repository'): their values are read as target candidates, never as criteria
TARGET_FIELD_NAME = re.compile(r"\b(environment|env|url|urls|link|base[\s_-]*url|test[\s_-]*(site|url|env\w*)|"
                               r"application|app|apk|package|bundle(?:[\s_-]*id)?|endpoint|api|openapi|swagger|"
                               r"repo(?:sitory)?|host|domain|staging|sandbox)\b", re.I)


def special_fields(client: Client) -> tuple[str, dict[str, str]]:
    """(the acceptance-criteria field id, {field id: name} of the custom fields that name the application) - one call."""
    data = client.get("/rest/api/3/field")
    rows = [f for f in data.get("values", data if isinstance(data, list) else []) if isinstance(f, dict)]
    found = [f for f in rows if f.get("custom") and AC_FIELD_NAME.search(str(f.get("name", "")))]
    found.sort(key=lambda f: (not EXACT_AC_FIELD.match(str(f.get("name", ""))), str(f.get("id", ""))))
    ac = str(found[0].get("id", "")) if found else ""
    targets = {str(f["id"]): str(f.get("name", ""))[:80] for f in rows if f.get("custom") and f.get("id")
               and str(f.get("id")) != ac and TARGET_FIELD_NAME.search(str(f.get("name", "")))}
    return ac, dict(list(targets.items())[:20])


def _field_text(value) -> str:
    if isinstance(value, dict):
        if value.get("type") == "doc":
            return adf_to_text(value)
        return str(value.get("value") or value.get("name") or value.get("url") or "")
    if isinstance(value, list):
        return " ".join(_field_text(v) for v in value)
    return "" if value is None else str(value)


def acceptance_field(client: Client) -> str:
    """The id of the custom field that holds acceptance criteria (e.g. customfield_10045), or ''. A field named
    exactly 'Acceptance Criteria' wins over the variants ('AcceptanceCriteria', 'AC', 'Definition of Done')."""
    data = client.get("/rest/api/3/field")
    found = [f for f in data.get("values", data if isinstance(data, list) else [])
             if isinstance(f, dict) and f.get("custom") and AC_FIELD_NAME.search(str(f.get("name", "")))]
    found.sort(key=lambda f: (not EXACT_AC_FIELD.match(str(f.get("name", ""))), str(f.get("id", ""))))
    return str(found[0].get("id", "")) if found else ""


def myself(client: Client) -> dict:
    """Who the credential belongs to (the connection test). The email address is not returned."""
    data = client.get("/rest/api/3/myself")
    if not data.get("accountId"):
        raise AtlassianError("invalid_response", "the account answer has no account id")
    return {"account_id": str(data.get("accountId", "")), "display_name": str(data.get("displayName", "")),
            "active": bool(data.get("active", True)), "account_type": str(data.get("accountType", ""))}


def work_item_types(client: Client, project: str) -> list[dict]:
    """The work-item (issue) types of one project: [{'id', 'name', 'subtask', 'hierarchy_level'}]."""
    if not PROJECT_KEY.match(project or ""):
        raise ValueError("project must be a Jira project key such as SHOP")
    data = client.get(f"/rest/api/3/project/{project}")
    out = []
    for t in data.get("issueTypes") or []:
        if isinstance(t, dict) and WORK_ITEM_TYPE.match(str(t.get("name", ""))):
            out.append({"id": str(t.get("id", "")), "name": str(t["name"]), "subtask": bool(t.get("subtask")),
                        "hierarchy_level": int(t.get("hierarchyLevel") or 0)})
    return out


def count(client: Client, jql: str) -> int:
    """How many work items a query matches (Jira's approximate count: a preview, not an exact total)."""
    data = client.post_read("/rest/api/3/search/approximate-count", {"jql": jql})
    value = data.get("count")
    if not isinstance(value, int) or value < 0:
        raise AtlassianError("invalid_response", "the count answer has no count")
    return value


def type_counts(client: Client, project: str, types: list[dict] | None = None) -> list[dict]:
    """[{'name', 'count'}] for each (non-sub-task) type of a project: what an import would find, per type."""
    types = types if types is not None else work_item_types(client, project)
    out = []
    for t in [t for t in types if not t["subtask"]][:MAX_TYPES]:
        query = build_jql(project, (t["name"],), order=False)
        out.append({"name": t["name"], "count": count(client, query)})
    return out


def search(client: Client, jql: str, fields: list[str], next_page_token: str = "",
           max_results: int = PAGE_SIZE) -> dict:
    """One page: {'issues': [...], 'next_page_token': '...' or '', 'is_last': bool}."""
    body = {"jql": jql, "fields": fields, "maxResults": max_results}
    if next_page_token:
        body["nextPageToken"] = next_page_token
    page = client.post_read("/rest/api/3/search/jql", body)
    issues = page.get("issues")
    if not isinstance(issues, list):
        raise AtlassianError("invalid_response", "search answer has no issues list")
    token = page.get("nextPageToken") or ""
    return {"issues": issues, "next_page_token": token, "is_last": bool(page.get("isLast", not token))}


def get_issue(client: Client, key: str, fields: list[str]) -> dict:
    """One work item by key (GET /rest/api/3/issue/{key}); AtlassianError 'not_found' when it is gone or hidden."""
    if not ISSUE_KEY.match(key or ""):
        raise ValueError("not an issue key")
    return client.get(f"/rest/api/3/issue/{key}", {"fields": ",".join(fields)})


def remote_links(client: Client, key: str) -> list[dict]:
    """An issue's remote links (Confluence pages appear here when a page is linked to the story):
    [{'url', 'title', 'application', 'global_id'}]."""
    if not ISSUE_KEY.match(key or ""):
        raise ValueError("not an issue key")
    data = client.get(f"/rest/api/3/issue/{key}/remotelink")
    out = []
    for link in data.get("values", []):
        if not isinstance(link, dict):
            continue
        obj = link.get("object") or {}
        out.append({"url": str(obj.get("url", "")), "title": str(obj.get("title", "")),
                    "application": str((link.get("application") or {}).get("type", "")),
                    "global_id": str(link.get("globalId", ""))})
    return out


# ---------------------------------------------------------------- ADF -> text

def adf_to_text(node) -> str:
    """Plain text of an ADF document (or a plain string, as older fields have). Blocks end in a new line; list
    items start with '- ' or '1. '; headings with '#'."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    lines: list[str] = []

    def inline(n) -> str:
        if not isinstance(n, dict):
            return ""
        t = n.get("type")
        if t == "text":
            return str(n.get("text", ""))
        if t == "hardBreak":
            return "\n"
        if t in ("mention", "emoji"):
            return str((n.get("attrs") or {}).get("text", ""))
        if t == "inlineCard":
            return str((n.get("attrs") or {}).get("url", ""))
        return "".join(inline(c) for c in n.get("content") or [])

    def block(n, prefix: str = ""):
        if not isinstance(n, dict):
            return
        t = n.get("type")
        content = n.get("content") or []
        if t in ("paragraph", "heading"):
            text = "".join(inline(c) for c in content).strip()
            if text:
                level = (n.get("attrs") or {}).get("level", 1) if t == "heading" else 0
                lines.append(prefix + ("#" * int(level) + " " if level else "") + text)
        elif t in ("bulletList", "orderedList"):
            for i, item in enumerate(content, 1):
                mark = f"{i}. " if t == "orderedList" else "- "
                first = True
                for child in (item.get("content") or []) if isinstance(item, dict) else []:
                    block(child, prefix + (mark if first else "   "))
                    first = False
        elif t == "codeBlock":
            lines.append("".join(inline(c) for c in content))
        elif t == "table":
            for row in content:
                if isinstance(row, dict):
                    cells = [adf_to_text({"type": "doc", "content": c.get("content") or []}).replace("\n", " ")
                             for c in row.get("content") or [] if isinstance(c, dict)]
                    lines.append(prefix + " | ".join(cells))
        elif t in ("doc", "blockquote", "panel", "expand", "nestedExpand", "layoutSection", "layoutColumn"):
            for c in content:
                block(c, prefix)
        elif t == "rule":
            lines.append("---")
        else:
            text = "".join(inline(c) for c in content).strip()
            if text:
                lines.append(prefix + text)

    block(node)
    return "\n".join(lines).strip()


# ---------------------------------------------------------------- normalize

def normalize(issue: dict, connection: Connection, *, ac_field: str = "", target_fields: dict | None = None,
              retrieved_at: datetime | None = None,
              version: int = 1) -> dict:
    """One Jira issue -> {'source': SourceRef, 'story': {...plain fields...}, 'text': the hashed content}.

    The hash covers what a tester reads (summary, description, acceptance criteria, type, status, labels,
    links), so a change in any of them is a new version; a re-read of unchanged content is not."""
    key = str(issue.get("key", ""))
    if not ISSUE_KEY.match(key):
        raise ValueError(f"not an issue key: {key!r}")
    f = issue.get("fields") or {}
    if not isinstance(f, dict):
        raise ValueError(f"{key}: fields missing")
    description = adf_to_text(f.get("description"))
    criteria = adf_to_text(f.get(ac_field)) if ac_field else ""
    links = []
    for link in f.get("issuelinks") or []:
        if not isinstance(link, dict):
            continue
        for side, word in (("outwardIssue", "outward"), ("inwardIssue", "inward")):
            other = link.get(side)
            if isinstance(other, dict) and ISSUE_KEY.match(str(other.get("key", ""))):
                links.append({"key": other["key"], "type": str((link.get("type") or {}).get(word, ""))})
    story = {
        "key": key,
        "id": str(issue.get("id", "")),
        "project": str((f.get("project") or {}).get("key", "") or key.split("-")[0]),
        "type": str((f.get("issuetype") or {}).get("name", "")),
        "summary": str(f.get("summary") or "").strip(),
        "status": str((f.get("status") or {}).get("name", "")),
        "priority": str((f.get("priority") or {}).get("name", "")),
        "labels": sorted(str(x) for x in f.get("labels") or []),
        "description": description,
        "acceptance_criteria": criteria,
        "acceptance_field": ac_field,
        "links": sorted(links, key=lambda x: (x["key"], x["type"])),
        "parent": str((f.get("parent") or {}).get("key", "")),
        "created": parse_time(f["created"]).isoformat() if f.get("created") else "",
    }
    app_fields = {name: _field_text(f.get(fid)).strip()[:500] for fid, name in (target_fields or {}).items()}
    app_fields = {k: v for k, v in app_fields.items() if v}
    if app_fields:  # (only then: a story without such fields keeps its content hash)
        story["app_fields"] = app_fields
    text = "\n".join([story["summary"], story["type"], story["status"], " ".join(story["labels"]),
                      story["description"], story["acceptance_criteria"],
                      " ".join(f"{x['type']}:{x['key']}" for x in story["links"])]
                     + [f"{k}: {v}" for k, v in sorted(app_fields.items())])
    if not story["summary"]:
        raise ValueError(f"{key}: no summary")
    source = SourceRef(tenant_id=connection.tenant_id, connection_id=connection.id, kind=SourceKind.jira_issue,
                       source_id=key, version=version, updated=parse_time(f.get("updated")),
                       url=f"{connection.site_url}/browse/{key}", title=story["summary"][:500],
                       content_hash=content_hash(text), retrieved_at=retrieved_at or datetime.now(UTC),
                       parent_id=story["parent"])
    return {"source": source, "story": story, "text": text}
