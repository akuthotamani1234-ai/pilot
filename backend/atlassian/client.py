"""The HTTP clients for Atlassian Cloud (Jira, Confluence): Client reads; WriteClient is the only way to write.

  auth        Basic: the connection's email + the token read from the secret NAMED by token_ref, at request time
              (the token is never kept on the client object's public fields, never logged, never in an error)
  read-only   GET only, plus the read-only search POST endpoints in READ_POSTS; anything else is refused here
  retries     429 / 502 / 503 / 504 and network errors: wait for Retry-After (capped) or back off exponentially
  401         stops at once: "token expired or revoked" (no retry loop)
  redirects   never followed (a redirect to another host could carry the credential away)
  size        a response bigger than MAX_BYTES is refused
Tests point base_url at a local mock server: only http(s)://127.0.0.1 / localhost is accepted for that.

WriteClient (Phase 5 write-back) adds exactly two writes - create an issue, add a comment (WRITE_PATHS) - with its
own token (a separate secret, never the read token). Only backend/atlassian/writeback.send uses it, and only for a
write a named person approved, with write-back switched on by the server owner. A write is never retried after a
network error or a 5xx (it may have arrived): writeback.send looks in Jira for its marker before it tries again.
"""
from __future__ import annotations

import email.utils
import json
import os
import re
import time
from collections.abc import Callable
from urllib.parse import urlparse

import requests

from ..safety import redact, register_secret_names
from .models import LOOKS_LIKE_SECRET, Connection

# Jira POST endpoints that only read: search, its count, and the JQL syntax check
READ_POSTS = frozenset({"/rest/api/3/search/jql", "/rest/api/3/search/approximate-count", "/rest/api/3/jql/parse"})
RETRY_STATUS = frozenset({429, 502, 503, 504})
# the only writes there are: create an issue, add a comment to an issue (WriteClient.post_write)
WRITE_PATHS = (re.compile(r"/rest/api/3/issue"), re.compile(r"/rest/api/3/issue/[A-Z][A-Z0-9_]{0,19}-\d{1,9}/comment"))
MAX_BYTES = 10 * 1024 * 1024
USER_AGENT = "Qpilot-RequirementsIntelligence/1"


class AtlassianError(Exception):
    """kind: auth_missing | auth_expired | forbidden | not_found | bad_request | rate_limited | server | network |
    redirect | too_large | invalid_response | refused"""

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind, self.status = kind, status

    def __str__(self):
        return f"{self.kind}: {super().__str__()}"


def env_secret(name: str) -> str:
    return os.environ.get(name, "")


def _loopback(url: str) -> bool:
    p = urlparse(url)
    return p.scheme in ("http", "https") and p.hostname in ("127.0.0.1", "localhost") and not p.path.strip("/")


def retry_after_seconds(value: str | None, now: float | None = None) -> float | None:
    """Retry-After is seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - (now if now is not None else time.time()))


class Client:
    def __init__(self, connection: Connection, *, secret: Callable[[str], str] = env_secret, base_url: str = "",
                 session: requests.Session | None = None, max_retries: int = 4, max_wait: float = 60.0,
                 backoff: float = 1.0, timeout: float = 30.0, sleep: Callable[[float], None] = time.sleep):
        if base_url and not _loopback(base_url):
            raise AtlassianError("refused", "base_url is only for a local mock server (127.0.0.1)")
        register_secret_names(connection.token_ref)  # (its value is redacted everywhere from now on)
        self.connection = connection
        self.base_url = (base_url or connection.site_url).rstrip("/")
        self._secret = secret
        self.session = session or requests.Session()
        self.max_retries, self.max_wait, self.backoff, self.timeout = max_retries, max_wait, backoff, timeout
        self.sleep = sleep
        self.calls = 0  # requests actually sent (tests, cost)

    # -- secrets never leave this object
    def _token(self) -> str:
        token = self._secret(self.connection.token_ref) or ""
        if not token:
            raise AtlassianError("auth_missing", f"the secret {self.connection.token_ref} is not set")
        return token

    def _clean(self, text: str) -> str:
        token = self._secret(self.connection.token_ref) or ""
        text = redact(text or "", [token] if token else None) if token else redact(text or "")
        return LOOKS_LIKE_SECRET.sub("[REDACTED]", text)[:300]

    # -- the one way to call Atlassian
    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post_read(self, path: str, body: dict, params: dict | None = None) -> dict:
        """A read-only search POST (Jira's /search/jql takes its query in the body)."""
        if path not in READ_POSTS:
            raise AtlassianError("refused", f"POST {path} is not a read-only endpoint")
        return self._request("POST", path, params=params, payload=body)

    def _request(self, method: str, path: str, params: dict | None = None, payload: dict | None = None,
                 write: bool = False) -> dict:
        # (a second lock behind get / post_read: nothing in this package can send a write through this client)
        if write:
            if not (isinstance(self, WriteClient) and method == "POST" and any(p.fullmatch(path) for p in WRITE_PATHS)):
                raise AtlassianError("refused", f"{method} {path} is not an allowed write")
        elif method != "GET" and not (method == "POST" and path in READ_POSTS):
            raise AtlassianError("refused", f"{method} {path} would change Atlassian data: this client only reads")
        if not path.startswith("/") or "://" in path or ".." in path.split("/"):
            raise AtlassianError("refused", "path must be a site-relative API path")
        url = self.base_url + path
        auth = (self.connection.email, self._token())
        attempt = 0
        while True:
            attempt += 1
            try:
                self.calls += 1
                r = self.session.request(method, url, params=params, json=payload, auth=auth, timeout=self.timeout,
                                         allow_redirects=False, stream=True,
                                         headers={"Accept": "application/json", "User-Agent": USER_AGENT})
            except requests.RequestException as error:
                if write:  # (it may have arrived: never sent again blindly)
                    raise AtlassianError("network", "the write may or may not have reached Atlassian ("
                                         + self._clean(type(error).__name__) + "); a retry checks Jira first") from None
                if attempt > self.max_retries:
                    raise AtlassianError("network", self._clean(f"{type(error).__name__}: {error}")) from None
                self.sleep(min(self.max_wait, self.backoff * 2 ** (attempt - 1)))
                continue
            status = r.status_code
            if write and status in RETRY_STATUS and status != 429:
                r.close()
                raise AtlassianError("server", f"HTTP {status}: the write may or may not have been applied; a retry "
                                               "checks Jira first", status)
            if status in RETRY_STATUS:
                wait = retry_after_seconds(r.headers.get("Retry-After"))
                r.close()
                if attempt > self.max_retries:
                    kind = "rate_limited" if status == 429 else "server"
                    raise AtlassianError(kind, f"HTTP {status} after {attempt} tries", status)
                self.sleep(min(self.max_wait, wait if wait is not None else self.backoff * 2 ** (attempt - 1)))
                continue
            if 300 <= status < 400:
                r.close()
                raise AtlassianError("redirect", f"HTTP {status}: redirects are not followed", status)
            body = self._read(r)
            if status == 401:
                raise AtlassianError("auth_expired", f"the token in {self.connection.token_ref} is expired, revoked "
                                                     "or wrong: update the secret", status)
            if status == 403:
                raise AtlassianError("forbidden", self._message(body, "no permission"), status)
            if status == 404:
                raise AtlassianError("not_found", self._message(body, "not found"), status)
            if status == 400:
                raise AtlassianError("bad_request", self._message(body, "bad request"), status)
            if status >= 400:
                raise AtlassianError("server", f"HTTP {status}: " + self._message(body, ""), status)
            if not body:
                return {}
            try:
                data = json.loads(body)
            except ValueError:
                raise AtlassianError("invalid_response", "the answer is not JSON", status) from None
            if not isinstance(data, (dict, list)):
                raise AtlassianError("invalid_response", "unexpected JSON", status)
            return data if isinstance(data, dict) else {"values": data}

    def _read(self, r) -> bytes:
        size = int(r.headers.get("Content-Length") or 0)
        if size > MAX_BYTES:
            r.close()
            raise AtlassianError("too_large", f"response of {size} bytes is over the limit")
        chunks, total = [], 0
        for chunk in r.iter_content(65536):
            total += len(chunk)
            if total > MAX_BYTES:
                r.close()
                raise AtlassianError("too_large", "response is over the limit")
            chunks.append(chunk)
        return b"".join(chunks)

    def _message(self, body: bytes, default: str) -> str:
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return self._clean(default)
        msgs = []
        if isinstance(data, dict):
            msgs += [str(m) for m in data.get("errorMessages") or []]
            msgs += [f"{k}: {v}" for k, v in (data.get("errors") or {}).items()] if isinstance(
                data.get("errors"), dict) else []
            if data.get("message"):
                msgs.append(str(data["message"]))
        return self._clean("; ".join(msgs) or default)


class WriteClient(Client):
    """Writes to Jira - two kinds only (WRITE_PATHS). Its connection's token_ref names the WRITE secret."""

    def post_write(self, path: str, body: dict) -> dict:
        if not any(p.fullmatch(path) for p in WRITE_PATHS):
            raise AtlassianError("refused", f"POST {path} is not an allowed write")
        return self._request("POST", path, payload=body, write=True)
