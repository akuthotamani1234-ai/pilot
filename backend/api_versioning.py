"""Gate I API versioning helpers. Legacy ``/api/...`` maps to v1.

Versioned paths use ``/api/v{N}/...``. Unsupported versions are rejected
without guessing a newer contract.
"""
from __future__ import annotations

import re

SUPPORTED = frozenset({1})
_VERSIONED = re.compile(r"^/api/v(\d+)(/.*)?$")


def resolve_path(path: str) -> dict:
    """Normalize a request path to an API version and unversioned resource path."""
    raw = path or "/"
    match = _VERSIONED.match(raw)
    if match:
        version = int(match.group(1))
        resource = match.group(2) or "/"
        if version not in SUPPORTED:
            return {
                "ok": False,
                "version": version,
                "resource": resource,
                "legacy": False,
                "reason": f"API v{version} is not supported; use v1",
            }
        return {"ok": True, "version": version, "resource": resource, "legacy": False, "reason": ""}
    if raw == "/api" or raw.startswith("/api/"):
        resource = raw[4:] or "/"
        if not resource.startswith("/"):
            resource = "/" + resource
        return {"ok": True, "version": 1, "resource": resource, "legacy": True, "reason": ""}
    return {"ok": False, "version": None, "resource": raw, "legacy": False,
            "reason": "not an /api path"}


def versioned_path(resource: str, *, version: int = 1) -> str:
    """Build a canonical versioned path for docs and clients."""
    if version not in SUPPORTED:
        raise ValueError(f"unsupported API version {version}")
    res = resource if resource.startswith("/") else f"/{resource}"
    return f"/api/v{version}{res}"
