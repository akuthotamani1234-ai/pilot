"""A local mock of one Atlassian Cloud site (the parts Requirements Intelligence reads), on 127.0.0.1.

Jira: /project/search (startAt paging), /field, POST /search/jql (nextPageToken paging), /issue/{key}/remotelink.
Confluence: /wiki/api/v2/spaces, /spaces/{id}/pages (cursor paging, newest change first), /pages/{id},
/pages?space-id&title. Shapes follow Atlassian's public Cloud APIs. It checks Basic auth, can inject faults (429 with Retry-After, 401, 503, redirects, big
bodies), expire page tokens, and records every request so tests can prove the client only reads.
No real tenant data: every story is generated here.
"""
from __future__ import annotations

import base64
import json
import re
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

EMAIL, TOKEN = "qa@acme.test", "mock-token-value-123"
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def jira_time(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def adf(*paragraphs: str) -> dict:
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs]}


def conf_time(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def page(page_id: str, title: str, body: str, space_id: str = "100", version: int = 1,
         when: datetime = T0, status: str = "current", parent: str = "") -> dict:
    return {"id": page_id, "title": title, "status": status, "spaceId": space_id, "parentId": parent or None,
            "version": {"number": version, "createdAt": conf_time(when)},
            "body": {"storage": {"value": body, "representation": "storage"}},
            "_links": {"webui": f"/spaces/ENG/pages/{page_id}/{title.replace(' ', '+')}"}}


def story(key: str, summary: str, updated: datetime, description: str = "", ac: str = "", **fields) -> dict:
    f = {"summary": summary, "description": adf(description) if description else None,
         "issuetype": {"name": "Story"}, "status": {"name": "To Do"}, "labels": [], "priority": {"name": "Medium"},
         "updated": jira_time(updated), "created": jira_time(T0), "issuelinks": [],
         "project": {"key": key.split("-")[0]}, "customfield_10045": adf(ac) if ac else None}
    f.update(fields)
    return {"id": str(10000 + int(key.split("-")[1])), "key": key, "fields": f}


class MockJira:
    def __init__(self):
        self.issues: dict[str, dict] = {}
        self.projects = [{"id": "1", "key": "SHOP", "name": "Shop"}]
        self.fields = [{"id": "summary", "name": "Summary", "custom": False},
                       {"id": "customfield_10045", "name": "Acceptance Criteria", "custom": True}]
        self.faults: list[dict] = []  # {"path": prefix, "status": 429, "headers": {...}, "body": "..."}
        self.requests: list[dict] = []
        self.generation = 0  # page tokens of older generations are 'expired'
        self.remote_links: dict[str, list[dict]] = {}
        self.spaces = [{"id": "100", "key": "ENG", "name": "Engineering", "type": "global", "status": "current"}]
        self.pages: dict[str, dict] = {}
        self.forbidden: set[str] = set()  # page ids answered 403
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def add_stories(self, n: int, project: str = "SHOP", start: int = 1, every: timedelta = timedelta(minutes=5)):
        for i in range(start, start + n):
            key = f"{project}-{i}"
            self.issues[key] = story(key, f"Story {i}", T0 + every * i, f"Description of story {i}",
                                     f"Given story {i}, when used, then it works.")

    def touch(self, key: str, when: datetime, **changes):
        f = self.issues[key]["fields"]
        f.update(changes)
        f["updated"] = jira_time(when)

    def fail(self, path: str, status: int, times: int = 1, headers: dict | None = None, body: str = ""):
        for _ in range(times):
            self.faults.append({"path": path, "status": status, "headers": headers or {}, "body": body})

    def expire_tokens(self):
        self.generation += 1

    def add_page(self, page_id: str, title: str, body: str, **kw) -> dict:
        self.pages[page_id] = page(page_id, title, body, **kw)
        return self.pages[page_id]

    def edit_page(self, page_id: str, body: str, when: datetime):
        p = self.pages[page_id]
        p["body"]["storage"]["value"] = body
        p["version"] = {"number": p["version"]["number"] + 1, "createdAt": conf_time(when)}

    def _token(self, offset: int) -> str:
        return base64.b64encode(f"{self.generation}:{offset}".encode()).decode()

    def _confluence(self, path: str, q: dict):
        """(status, body) for a Confluence v2 GET, or None when the path is not Confluence."""
        limit = int(q.get("limit", 25))
        start = int(base64.b64decode(q["cursor"]).decode().split(":")[1]) if q.get("cursor") else 0
        if path == "/wiki/api/v2/spaces":
            keys = set(q["keys"].split(",")) if q.get("keys") else None
            found = [sp for sp in self.spaces if keys is None or sp["key"] in keys]
            chunk = found[start:start + limit]
            links = {"next": f"/wiki/api/v2/spaces?cursor={self._token(start + limit)}&limit={limit}"} \
                if start + limit < len(found) else {}
            return 200, {"results": chunk, "_links": links}
        if m := re.fullmatch(r"/wiki/api/v2/spaces/(\d+)/pages", path):
            found = sorted((p for p in self.pages.values() if p["spaceId"] == m.group(1) and p["status"] == "current"),
                           key=lambda p: p["version"]["createdAt"], reverse=True)
            chunk = found[start:start + limit]
            links = {"next": f"{path}?cursor={self._token(start + limit)}&limit={limit}"} \
                if start + limit < len(found) else {}
            return 200, {"results": chunk, "_links": links}
        if m := re.fullmatch(r"/wiki/api/v2/pages/(\d+)", path):
            if m.group(1) in self.forbidden:
                return 403, {"errors": [{"status": 403, "title": "Forbidden"}], "message": "no permission"}
            found = self.pages.get(m.group(1))
            if not found or found["status"] == "deleted":
                return 404, {"errors": [{"status": 404, "title": "Not Found"}]}
            return 200, found
        if path == "/wiki/api/v2/pages":
            found = [p for p in self.pages.values() if p["spaceId"] == q.get("space-id") and p["title"] == q.get("title")
                     and p["status"] == "current"]
            return 200, {"results": found[:limit], "_links": {}}
        if m := re.fullmatch(r"/rest/api/3/issue/([A-Z][A-Z0-9_]*-\d+)/remotelink", path):
            if m.group(1) not in self.issues:
                return 404, {"errorMessages": ["Issue does not exist or you do not have permission to see it."]}
            return 200, self.remote_links.get(m.group(1), [])
        return None

    # ------------------------------------------------------------ JQL (the subset the connector writes)
    def _matching(self, jql: str) -> list[dict]:
        project = re.search(r"project = ([A-Z][A-Z0-9_]*)", jql)
        since = re.search(r'updated >= "(\d{4})/(\d\d)/(\d\d) (\d\d):(\d\d)"', jql)
        types = re.search(r"issuetype in \(([^)]*)\)", jql)
        names = re.findall(r'"((?:[^"\\]|\\.)*)"', types.group(1)) if types else None
        out = []
        for issue in self.issues.values():
            f = issue["fields"]
            if project and f["project"]["key"] != project.group(1):
                continue
            if names is not None and f["issuetype"]["name"] not in names:
                continue
            if since:
                limit = datetime(*map(int, since.groups()), tzinfo=UTC)
                if datetime.strptime(f["updated"], "%Y-%m-%dT%H:%M:%S.000+0000").replace(tzinfo=UTC) < limit:
                    continue
            out.append(issue)
        return sorted(out, key=lambda i: (i["fields"]["updated"], int(i["key"].split("-")[1])))

    def _handler(self):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status: int, data=None, headers: dict | None = None, raw: bytes | None = None):
                body = raw if raw is not None else json.dumps(data if data is not None else {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _handle(self, method: str):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                path = urlparse(self.path).path
                query = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                auth = self.headers.get("Authorization", "")
                ok = auth == "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
                with mock.lock:
                    mock.requests.append({"method": method, "path": path, "auth_ok": ok, "body": body})
                    fault = next((f for f in mock.faults if path.startswith(f["path"])), None)
                    if fault:
                        mock.faults.remove(fault)
                if fault:
                    return self._send(fault["status"], {"errorMessages": [fault["body"]]} if fault["body"] else {},
                                      fault["headers"])
                if not ok:
                    return self._send(401, {"errorMessages": ["Client must be authenticated"]})
                if method == "GET" and (answer := mock._confluence(path, query)) is not None:
                    return self._send(answer[0], raw=json.dumps(answer[1]).encode())
                if method == "GET" and path == "/rest/api/3/project/search":
                    start, size = int(query.get("startAt", 0)), int(query.get("maxResults", 50))
                    values = mock.projects[start:start + size]
                    return self._send(200, {"values": values, "startAt": start, "maxResults": size,
                                            "total": len(mock.projects), "isLast": start + size >= len(mock.projects)})
                if method == "GET" and path == "/rest/api/3/field":
                    return self._send(200, raw=json.dumps(mock.fields).encode())
                if method == "POST" and path == "/rest/api/3/search/jql":
                    matches = mock._matching(body.get("jql", ""))
                    size = int(body.get("maxResults", 50))
                    start = 0
                    if body.get("nextPageToken"):
                        gen, _, offset = base64.b64decode(body["nextPageToken"]).decode().partition(":")
                        if int(gen) != mock.generation:
                            return self._send(400, {"errorMessages": ["The provided next page token is invalid "
                                                                      "or expired."]})
                        start = int(offset)
                    page = matches[start:start + size]
                    wanted = set(body.get("fields") or [])
                    issues = [{**i, "fields": {k: v for k, v in i["fields"].items() if not wanted or k in wanted}}
                              for i in page]
                    data = {"issues": issues, "isLast": start + size >= len(matches)}
                    if not data["isLast"]:
                        data["nextPageToken"] = base64.b64encode(f"{mock.generation}:{start + size}".encode()).decode()
                    return self._send(200, data)
                return self._send(404, {"errorMessages": ["No such endpoint in the mock"]})

            def do_GET(self):
                self._handle("GET")

            def do_POST(self):
                self._handle("POST")

            def do_PUT(self):
                self._handle("PUT")

            def do_DELETE(self):
                self._handle("DELETE")

        return Handler


MockAtlassian = MockJira  # (one mock site answers both Jira and Confluence paths)
