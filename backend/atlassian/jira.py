"""Read Jira Cloud: projects, the acceptance-criteria field, stories by JQL (paged), and one normalized story.

All calls are reads through client.Client. Jira Cloud's current search is POST /rest/api/3/search/jql, paged with
nextPageToken (the older /rest/api/3/search with startAt is being retired). Descriptions arrive in Atlassian
Document Format (ADF); adf_to_text keeps the words, headings, list items and line breaks.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from .client import AtlassianError, Client
from .models import ISSUE_KEY, Connection, SourceKind, SourceRef, content_hash, parse_time

PAGE_SIZE = 50
STORY_TYPES = ("Story",)
BASE_FIELDS = ["summary", "description", "issuetype", "status", "labels", "priority", "updated", "created",
               "issuelinks", "parent", "project"]
AC_FIELD_NAME = re.compile(r"\bacceptance\s+criteri(a|on)\b", re.I)
# JQL compares dates in the Jira user's own time zone and to the minute; an overlap of 14 h + 1 min covers every
# time zone. Re-read issues are recognized by their content hash and create no new version.
OVERLAP = timedelta(hours=14, minutes=1)
PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")


# ---------------------------------------------------------------- JQL

def jql_string(value: str) -> str:
    """A JQL string literal: quotes and backslashes escaped, no line breaks."""
    value = re.sub(r"[\r\n]+", " ", value or "")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_jql(project: str, issue_types=STORY_TYPES, extra: str = "", since: datetime | None = None) -> str:
    """project = KEY AND issuetype in ("Story") [AND (extra)] [AND updated >= "..."] ORDER BY updated ASC, key ASC

    ORDER BY updated ascending lets the sync move its high-water mark forward page by page."""
    if not PROJECT_KEY.match(project or ""):
        raise ValueError("project must be a Jira project key such as SHOP")
    parts = [f"project = {project}"]
    if issue_types:
        parts.append("issuetype in (" + ", ".join(jql_string(t) for t in issue_types) + ")")
    if extra:
        if re.search(r"\border\s+by\b", extra, re.I):
            raise ValueError("the extra filter cannot contain ORDER BY")
        parts.append(f"({extra})")
    if since is not None:
        start = (since.astimezone(UTC) - OVERLAP).strftime("%Y/%m/%d %H:%M")
        parts.append(f'updated >= "{start}"')
    return " AND ".join(parts) + " ORDER BY updated ASC, key ASC"


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


def acceptance_field(client: Client) -> str:
    """The id of the custom field named 'Acceptance Criteria' (e.g. customfield_10045), or ''."""
    data = client.get("/rest/api/3/field")
    for f in data.get("values", data if isinstance(data, list) else []):
        if isinstance(f, dict) and f.get("custom") and AC_FIELD_NAME.search(str(f.get("name", ""))):
            return str(f.get("id", ""))
    return ""


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

def normalize(issue: dict, connection: Connection, *, ac_field: str = "", retrieved_at: datetime | None = None,
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
    text = "\n".join([story["summary"], story["type"], story["status"], " ".join(story["labels"]),
                      story["description"], story["acceptance_criteria"],
                      " ".join(f"{x['type']}:{x['key']}" for x in story["links"])])
    if not story["summary"]:
        raise ValueError(f"{key}: no summary")
    source = SourceRef(tenant_id=connection.tenant_id, connection_id=connection.id, kind=SourceKind.jira_issue,
                       source_id=key, version=version, updated=parse_time(f.get("updated")),
                       url=f"{connection.site_url}/browse/{key}", title=story["summary"][:500],
                       content_hash=content_hash(text), retrieved_at=retrieved_at or datetime.now(UTC),
                       parent_id=story["parent"])
    return {"source": source, "story": story, "text": text}
