"""Read Confluence Cloud: spaces, pages (v2 API), and a page's requirement content in plain sections.

All calls are GETs through client.Client (the same client, credentials and safety rules as Jira).

  spaces()          GET /wiki/api/v2/spaces (cursor paging, optional keys filter)
  space_pages()     GET /wiki/api/v2/spaces/{id}/pages, newest change first, with the storage-format body
  get_page()        GET /wiki/api/v2/pages/{id}
  find_page()       GET /wiki/api/v2/pages?title=...&space-id=... (a link written as space + title)
  extract()         storage-format XHTML -> sections (heading path, paragraphs, list items, table rows, code,
                    tasks), requirement-looking sections marked, links to pages / Jira issues, size limits
  normalize()       a page -> SourceRef (Confluence's own version number) + content + hash

Nothing here creates acceptance criteria (Phase 3): sections are kept word for word with their headings, so a later
criterion can quote them exactly.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

from .client import AtlassianError, Client
from .models import ISSUE_KEY, PAGE_ID, Connection, SourceKind, SourceRef, content_hash, parse_time

PAGE_SIZE = 25
MAX_SECTIONS = 400
MAX_BLOCKS = 400  # per section
MAX_BLOCK_CHARS = 4000
SPACE_KEY = re.compile(r"^[A-Za-z0-9~][A-Za-z0-9_~-]{0,254}$")
REQUIREMENT_HEADING = re.compile(r"\b(requirements?|acceptance|criteria|business rules?|rules|validations?|"
                                 r"user stor(y|ies)|scope|scenarios?|use cases?|constraints?|specification)\b", re.I)
REQUIREMENT_TEXT = re.compile(r"\b(must|shall|must not|shall not|is required|are required|should not|"
                              r"acceptance criteria)\b|^\s*(given|when|then)\b", re.I | re.M)
ISSUE_IN_TEXT = re.compile(r"(?<![A-Za-z0-9-])([A-Z][A-Z0-9_]{1,19}-[1-9][0-9]{0,9})(?![A-Za-z0-9-])")
PAGE_URL = re.compile(r"/wiki/spaces/[^/]+/pages/(\d{1,20})(?:/|$)")
BROWSE_URL = re.compile(r"/browse/([A-Z][A-Z0-9_]{0,19}-[1-9][0-9]{0,9})(?:[/?#]|$)")


# ---------------------------------------------------------------- reads

def _cursor(page: dict) -> str:
    """v2 paging: _links.next is '/wiki/api/v2/...?cursor=XYZ&limit=..' -> 'XYZ' (or '')."""
    nxt = ((page.get("_links") or {}).get("next")) or ""
    return (parse_qs(urlparse(nxt).query).get("cursor") or [""])[0]


def spaces(client: Client, keys: list[str] | None = None) -> list[dict]:
    out, cursor = [], ""
    params = {"limit": PAGE_SIZE}
    if keys:
        bad = [k for k in keys if not SPACE_KEY.match(k)]
        if bad:
            raise ValueError(f"not a space key: {bad[0]!r}")
        params["keys"] = ",".join(keys)
    while True:
        page = client.get("/wiki/api/v2/spaces", {**params, **({"cursor": cursor} if cursor else {})})
        for s in page.get("results") or []:
            if isinstance(s, dict) and s.get("id") and SPACE_KEY.match(str(s.get("key", ""))):
                out.append({"id": str(s["id"]), "key": s["key"], "name": str(s.get("name", "")),
                            "type": str(s.get("type", "")), "status": str(s.get("status", ""))})
        cursor = _cursor(page)
        if not cursor:
            return out


def space_pages(client: Client, space_id: str, cursor: str = "", limit: int = PAGE_SIZE) -> dict:
    """One page of a space's pages, most recently changed first: {'pages': [...], 'cursor': next or ''}."""
    if not PAGE_ID.match(str(space_id)):
        raise ValueError("space id must be numeric")
    params = {"limit": limit, "sort": "-modified-date", "body-format": "storage", "status": "current"}
    if cursor:
        params["cursor"] = cursor
    page = client.get(f"/wiki/api/v2/spaces/{space_id}/pages", params)
    results = page.get("results")
    if not isinstance(results, list):
        raise AtlassianError("invalid_response", "page list has no results")
    return {"pages": results, "cursor": _cursor(page)}


def get_page(client: Client, page_id: str) -> dict:
    if not PAGE_ID.match(str(page_id)):
        raise ValueError("page id must be numeric")
    return client.get(f"/wiki/api/v2/pages/{page_id}", {"body-format": "storage"})


def find_page(client: Client, space_id: str, title: str) -> str:
    """The id of the page with this exact title in this space, or ''."""
    if not PAGE_ID.match(str(space_id)) or not title or len(title) > 255:
        return ""
    page = client.get("/wiki/api/v2/pages", {"space-id": space_id, "title": title, "limit": 2})
    for p in page.get("results") or []:
        if isinstance(p, dict) and p.get("title") == title and PAGE_ID.match(str(p.get("id", ""))):
            return str(p["id"])
    return ""


# ---------------------------------------------------------------- storage format -> sections

class _Extractor(HTMLParser):
    BLOCKS = {"p": "paragraph", "li": "list_item", "tr": "table_row", "pre": "code", "blockquote": "paragraph",
              "ac:task-body": "task", "ac:plain-text-body": "code"}
    SKIP = {"ac:task-status", "ac:task-id", "ac:placeholder", "ac:task-uuid"}

    def __init__(self, host: str):
        super().__init__(convert_charrefs=True)
        self.host = host
        self.sections: list[dict] = [{"heading": "", "level": 0, "path": [], "blocks": []}]
        self.path: list[tuple[int, str]] = []
        self.heading: list[str] | None = None
        self.heading_level = 0
        self.stack: list[tuple[str, list[str]]] = []  # open blocks: (kind, text parts)
        self.cells: list[list[str]] | None = None
        self.cell: list[str] | None = None
        self.macro: list[str] = []
        self.param: str | None = None
        self.param_text: list[str] = []
        self.page_ids: list[str] = []
        self.page_titles: list[tuple[str, str]] = []
        self.issues: list[str] = []
        self.external = 0
        self.truncated = False
        self.all_text: list[str] = []
        self.skip = 0  # inside ac:task-status / ac:task-id / ac:placeholder: not page content

    # -- text goes to the innermost open thing
    def _text_target(self) -> list[str] | None:
        if self.skip:
            return []
        if self.param is not None:
            return self.param_text
        if self.heading is not None:
            return self.heading
        if self.cell is not None:
            return self.cell
        return self.stack[-1][1] if self.stack else None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.heading is not None and (tag in self.BLOCKS or tag in ("table", "ul", "ol")
                                         or re.fullmatch(r"h[1-6]", tag)):
            self._close_heading()  # (malformed: a heading never closed before the next block)
        if tag in ("p", "li", "ul", "ol", "table", "pre", "blockquote") and self.stack and \
                self.stack[-1][0] == "paragraph" and self.cell is None:
            kind, parts = self.stack.pop()  # (HTML: a paragraph ends where a list, table or paragraph starts)
            self._block(kind, _clean("".join(parts)))
        if tag in self.SKIP:
            self.skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.heading, self.heading_level = [], int(tag[1])
        elif tag == "br":
            target = self._text_target()
            if target is not None:
                target.append(" ")
        elif tag == "tr":
            self.cells = []
        elif tag in ("td", "th") and self.cells is not None:
            self.cell = []
        elif tag == "p" and self.stack and self.stack[-1][0] in ("list_item", "task"):
            if self.stack[-1][1]:
                self.stack[-1][1].append(" ")  # (<li><p>text</p></li>: the paragraph is the list item's text)
        elif tag in self.BLOCKS and tag != "tr":
            if tag == "li" and self.stack and self.stack[-1][0] == "list_item" and "".join(self.stack[-1][1]).strip():
                # (a nested list: the parent item's own words come first, in reading order)
                self._block("list_item", _clean("".join(self.stack[-1][1])))
                self.stack[-1][1].clear()
            self.stack.append((self.BLOCKS[tag], []))
        elif tag == "ac:structured-macro":
            self.macro.append(str(a.get("ac:name", "")))
        elif tag == "ac:parameter":
            self.param, self.param_text = str(a.get("ac:name", "")), []
        elif tag == "ri:page":
            title, space = a.get("ri:content-title"), a.get("ri:space-key") or ""
            if a.get("ri:content-id") and PAGE_ID.match(a["ri:content-id"]):
                self.page_ids.append(a["ri:content-id"])
            elif title:
                self.page_titles.append((space, title))
            if title and (target := self._text_target()) is not None:
                target.append(title)
        elif tag == "a" and a.get("href"):
            self._url(a["href"])

    def _url(self, href: str):
        p = urlparse(href)
        if p.scheme and (p.hostname or "").lower() != self.host:
            self.external += 1
            return
        if m := PAGE_URL.search(p.path):
            self.page_ids.append(m.group(1))
        elif m := BROWSE_URL.search(p.path):
            self.issues.append(m.group(1))
        elif "pageId" in (q := parse_qs(p.query)) and PAGE_ID.match(q["pageId"][0]):
            self.page_ids.append(q["pageId"][0])

    def unknown_decl(self, data):
        if data.startswith("CDATA["):  # (a code macro's body)
            self.handle_data(data[6:])

    def _close_heading(self):
        text = _clean("".join(self.heading or []))
        self.heading = None
        if not text:
            return
        while self.path and self.path[-1][0] >= self.heading_level:
            self.path.pop()
        self.path.append((self.heading_level, text))
        self.all_text.append(text)
        if len(self.sections) > MAX_SECTIONS:  # (sections[0] holds text before the first heading)
            self.truncated = True
        else:
            self.sections.append({"heading": text, "level": self.heading_level,
                                  "path": [t for _, t in self.path], "blocks": []})

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif re.fullmatch(r"h[1-6]", tag) and self.heading is not None:
            self._close_heading()
        elif tag in ("td", "th") and self.cell is not None and self.cells is not None:
            self.cells.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.cells is not None:
            self._block("table_row", " | ".join(_clean("".join(c)) for c in self.cells))
            self.cells = None
        elif tag == "ac:parameter" and self.param is not None:
            value = _clean("".join(self.param_text))
            if self.macro and self.macro[-1] == "jira" and self.param == "key" and ISSUE_KEY.match(value):
                self.issues.append(value)
            self.param = None
        elif tag == "ac:structured-macro" and self.macro:
            self.macro.pop()
        elif tag == "p" and self.stack and self.stack[-1][0] in ("list_item", "task"):
            pass
        elif tag in self.BLOCKS and tag != "tr" and self.stack and self.stack[-1][0] == self.BLOCKS[tag]:
            kind, parts = self.stack.pop()
            text = "".join(parts)
            self._block(kind, text if kind == "code" else _clean(text))

    def _block(self, kind: str, text: str):
        if not text.strip():
            return
        self.all_text.append(text)
        section = self.sections[-1]
        if len(section["blocks"]) >= MAX_BLOCKS:
            self.truncated = True
            return
        if len(text) > MAX_BLOCK_CHARS:
            text, self.truncated = text[:MAX_BLOCK_CHARS], True
        section["blocks"].append({"type": kind, "text": text})

    def handle_data(self, data):
        target = self._text_target()
        if target is not None:
            target.append(data)
        elif data.strip():  # (loose text outside any block: keep it as a paragraph)
            self._block("paragraph", _clean(data))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract(storage: str, host: str) -> dict:
    """Storage-format XHTML -> {'sections', 'links', 'truncated', 'text'}. Malformed markup is read as far as it
    goes (HTMLParser does not stop at unclosed tags); 'text' is ALL the text, used for the content hash."""
    if not isinstance(storage, str):
        raise ValueError("page body is missing")
    parser = _Extractor(host.lower())
    parser.feed(storage)
    parser.close()
    if parser.heading is not None:
        parser._close_heading()
    while parser.stack:  # (unclosed blocks at the end of a malformed page, innermost last in reading order)
        kind, parts = parser.stack.pop(0)
        parser._block(kind, _clean("".join(parts)))
    sections = [s for s in parser.sections if s["blocks"] or s["heading"]]
    if len(sections) > MAX_SECTIONS:
        sections, parser.truncated = sections[:MAX_SECTIONS], True
    for s in sections:
        words = " ".join(b["text"] for b in s["blocks"])
        s["requirement_like"] = bool(REQUIREMENT_HEADING.search(" ".join(s["path"])) or REQUIREMENT_TEXT.search(words))
    text = "\n".join(parser.all_text)
    issues = list(dict.fromkeys(parser.issues + ISSUE_IN_TEXT.findall(text)))
    return {"sections": sections,
            "links": {"page_ids": list(dict.fromkeys(parser.page_ids)),
                      "page_titles": [list(t) for t in dict.fromkeys(parser.page_titles)],
                      "issues": issues, "external": parser.external},
            "truncated": parser.truncated, "text": text}


def page_ids_in(text: str, host: str) -> list[str]:
    """Confluence page ids in links found in plain text (a Jira description) on the same site."""
    out = []
    for url in re.findall(r"https://[^\s<>\")\]]+", text or ""):
        p = urlparse(unquote(url))
        if (p.hostname or "").lower() != host.lower():
            continue
        if m := PAGE_URL.search(p.path):
            out.append(m.group(1))
        elif (q := parse_qs(p.query).get("pageId")) and PAGE_ID.match(q[0]):
            out.append(q[0])
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- normalize

def normalize(page: dict, connection: Connection, *, space_key: str = "", retrieved_at: datetime | None = None
              ) -> dict:
    """One v2 page -> {'source': SourceRef (version = Confluence's own number), 'content': {...}, 'text': ...}."""
    page_id = str(page.get("id", ""))
    if not PAGE_ID.match(page_id):
        raise ValueError(f"not a page id: {page_id!r}")
    status = str(page.get("status", "current"))
    if status not in ("current", "draft"):
        raise ValueError(f"page {page_id} is {status}")
    version = page.get("version") or {}
    number = version.get("number")
    if not isinstance(number, int) or number < 1:
        raise ValueError(f"page {page_id}: no version number")
    title = str(page.get("title") or "").strip()
    if not title:
        raise ValueError(f"page {page_id}: no title")
    body = ((page.get("body") or {}).get("storage") or {}).get("value")
    found = extract(body, connection.host)
    webui = str((page.get("_links") or {}).get("webui") or "")
    url = (f"{connection.site_url}/wiki{webui}" if webui.startswith("/spaces/")
           else f"{connection.site_url}/wiki/spaces/{space_key or '~'}/pages/{page_id}")
    content = {"page_id": page_id, "title": title, "space_id": str(page.get("spaceId", "")), "space": space_key,
               "parent_id": str(page.get("parentId") or ""), "status": status, "confluence_version": number,
               "sections": found["sections"], "links": found["links"], "truncated": found["truncated"],
               "text_chars": len(found["text"])}
    source = SourceRef(tenant_id=connection.tenant_id, connection_id=connection.id, kind=SourceKind.confluence_page,
                       source_id=page_id, version=number, updated=parse_time(version.get("createdAt")), url=url,
                       title=title[:500], content_hash=content_hash(title + "\n" + found["text"]),
                       retrieved_at=retrieved_at or datetime.now(UTC), parent_id=content["parent_id"])
    return {"source": source, "content": content, "text": found["text"]}
