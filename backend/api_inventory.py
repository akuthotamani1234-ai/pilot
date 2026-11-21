"""API discovery: the website's own API calls that the browser made while exploring.

Only metadata is kept: method, a path pattern (ids become {id}), the names of query parameters (never their
values), response status, content type and the pages that made the call. No headers, cookies, request or response
bodies are stored, so tokens and personal data never reach the run folder.
"""
from __future__ import annotations

import re
import threading
from urllib.parse import parse_qsl, urlsplit

API_TYPES = ("xhr", "fetch")
_ID = re.compile(r"^(\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{16,}|"
                 r"[A-Za-z0-9_-]{32,})$", re.I)
_STATIC = re.compile(r"\.(js|mjs|css|map|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|mp4|webm)$", re.I)


def path_pattern(path: str) -> str:
    """'/api/v2/pim/employees/7' -> '/api/v2/pim/employees/{id}' (ids, uuids, long tokens in the path)."""
    parts = [("{id}" if _ID.match(p) else p) for p in path.split("/")]
    return "/".join(parts) or "/"


class ApiInventory:
    """Collects API calls seen in one run. Safe to call from Playwright event callbacks."""

    def __init__(self, hosts: set[str] | None = None, limit: int = 500):
        self.hosts = {h.lower() for h in (hosts or set()) if h}
        self.limit = limit
        self._calls: dict[tuple, dict] = {}
        self._lock = threading.Lock()

    def observe(self, response, page_url: str = "") -> None:
        try:
            request = response.request
            if request.resource_type not in API_TYPES:
                return
            parts = urlsplit(response.url)
            host = (parts.hostname or "").lower()
            if self.hosts and host not in self.hosts:
                return
            if _STATIC.search(parts.path):
                return
            method = request.method.upper()
            status = int(response.status)
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip()[:60]
        except Exception:
            return  # a response that went away before it could be read
        query = sorted({k for k, _v in parse_qsl(parts.query, keep_blank_values=True)})[:15]
        key = (method, host, path_pattern(parts.path))
        page = urlsplit(page_url).path if page_url else ""
        with self._lock:
            row = self._calls.get(key)
            if row is None:
                if len(self._calls) >= self.limit:
                    return
                row = self._calls[key] = {"method": method, "host": host, "path": key[2], "query_keys": [],
                                          "statuses": {}, "content_type": content_type, "calls": 0, "pages": []}
            row["calls"] += 1
            row["statuses"][str(status)] = row["statuses"].get(str(status), 0) + 1
            row["query_keys"] = sorted(set(row["query_keys"]) | set(query))
            if page and page not in row["pages"] and len(row["pages"]) < 5:
                row["pages"].append(page)

    def rows(self) -> list[dict]:
        with self._lock:
            return sorted((dict(r) for r in self._calls.values()), key=lambda r: (r["path"], r["method"]))

    def summary(self) -> dict:
        rows = self.rows()
        errors = sum(1 for r in rows if any(int(s) >= 400 for s in r["statuses"]))
        return {"endpoints": len(rows), "calls": sum(r["calls"] for r in rows), "with_errors": errors,
                "note": "Observed while exploring (method, path pattern, status). No headers, cookies or bodies kept.",
                "endpoints_list": rows}
