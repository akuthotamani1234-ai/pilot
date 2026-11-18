"""Gate I: SSO / hosting contract snapshot + JWT claim helper.

Records which IdP/hosting env vars operators would configure and can
structurally validate a bearer JWT (see ``oidc_jwt``). Never marks Gate I
complete — real SSO login + hosted multi-tenant ACLs remain open.
"""
from __future__ import annotations

import os


def _present(*names: str) -> str:
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return name
    return ""


def snapshot() -> dict:
    """Honest Gate I SSO/hosting readiness. ready stays False until live SSO proven."""
    issuer = _present("QPILOT_OIDC_ISSUER", "BLOWAI_OIDC_ISSUER", "OIDC_ISSUER")
    client = _present("QPILOT_OIDC_CLIENT_ID", "BLOWAI_OIDC_CLIENT_ID", "OIDC_CLIENT_ID")
    audience = _present("QPILOT_OIDC_AUDIENCE", "BLOWAI_OIDC_AUDIENCE", "OIDC_AUDIENCE")
    host = _present("QPILOT_DASHBOARD_HOST", "BLOWAI_DASHBOARD_HOST", "DASHBOARD_PUBLIC_URL")
    configured = bool(issuer or client or audience or host)
    return {
        "gate_i_complete": False,
        "ready": False,
        "configured": configured,
        "oidc_issuer_env": issuer or None,
        "oidc_client_env": client or None,
        "oidc_audience_env": audience or None,
        "dashboard_host_env": host or None,
        "jwt_helper": "backend.oidc_jwt.validate_bearer",
        "reason": (
            "OIDC/hosting env vars present + JWT claim helper; live SSO login + hosted multi-tenant ACLs not proven"
            if configured else
            "SSO/OIDC + hosted dashboard contracts not configured; JWT helper available; localhost Studio only"
        ),
    }


def validate_authorization_header(authorization: str | None) -> dict:
    """Validate ``Authorization: Bearer <jwt>`` using ``oidc_jwt`` (Gate I incomplete)."""
    from .oidc_jwt import validate_bearer

    given = (authorization or "").strip()
    token = given[7:].strip() if given.lower().startswith("bearer ") else given
    if not token:
        return {
            "ok": False,
            "gate_i_complete": False,
            "reason": "Authorization Bearer <jwt> required",
        }
    return validate_bearer(token)
