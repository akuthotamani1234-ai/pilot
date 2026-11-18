"""Gate I: optional dashboard bearer token (not multi-tenant auth).

When QPILOT_DASHBOARD_TOKEN / BLOWAI_DASHBOARD_TOKEN is unset, approvals APIs
stay open on localhost (Studio default). When set, Authorization: Bearer <token>
is required for approvals mutate/list. Hosting and real SSO remain open.
"""
from __future__ import annotations

import hmac
import os


def configured_token() -> str:
    return (
        os.getenv("QPILOT_DASHBOARD_TOKEN")
        or os.getenv("BLOWAI_DASHBOARD_TOKEN")
        or ""
    ).strip()


def required() -> bool:
    return bool(configured_token())


def authorize(authorization: str | None) -> dict:
    """Return {ok, reason}. Missing token config always allows (local Studio)."""
    expected = configured_token()
    if not expected:
        return {
            "ok": True,
            "required": False,
            "reason": "dashboard token not configured; localhost Studio allows open access",
        }
    given = (authorization or "").strip()
    if given.lower().startswith("bearer "):
        given = given[7:].strip()
    if given and hmac.compare_digest(given, expected):
        return {"ok": True, "required": True, "reason": "bearer token accepted"}
    return {
        "ok": False,
        "required": True,
        "reason": "Authorization Bearer token required for dashboard approvals",
    }


def snapshot() -> dict:
    return {
        "gate_i_complete": False,
        "token_configured": required(),
        "reason": (
            "Optional dashboard bearer token configured; SSO/hosting still open"
            if required() else
            "Dashboard token unset; approvals open on localhost only"
        ),
    }
