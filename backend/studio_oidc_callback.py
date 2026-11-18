"""Gate I: Studio OIDC authorization-code callback helper.

Exchanges ``code`` at the configured token endpoint, validates the JWT, and
returns a Studio session-shaped payload. Hosted IdP Studio SSO still open —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


def _env(*names: str, default: str = "") -> str:
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return default


def token_endpoint() -> str:
    explicit = _env("QPILOT_OIDC_TOKEN_URL", "OIDC_TOKEN_URL")
    if explicit:
        return explicit
    issuer = _env("QPILOT_OIDC_ISSUER", "BLOWAI_OIDC_ISSUER", "OIDC_ISSUER").rstrip("/")
    return f"{issuer}/token" if issuer else ""


def exchange_code(
    *,
    code: str,
    redirect_uri: str | None = None,
    client_id: str | None = None,
) -> dict:
    """POST authorization_code grant; validate access/id token when present."""
    from .oidc_jwt import validate_bearer

    endpoint = token_endpoint()
    if not endpoint:
        return {
            "ok": False,
            "gate_i_complete": False,
            "reason": "QPILOT_OIDC_ISSUER / QPILOT_OIDC_TOKEN_URL not configured",
        }
    if not (code or "").strip():
        return {
            "ok": False,
            "gate_i_complete": False,
            "reason": "authorization code required",
        }
    cid = client_id or _env(
        "QPILOT_OIDC_CLIENT_ID", "BLOWAI_OIDC_CLIENT_ID", "OIDC_CLIENT_ID",
        default="qpilot-studio",
    )
    redirect = redirect_uri or _env(
        "QPILOT_OIDC_REDIRECT_URI", "OIDC_REDIRECT_URI",
        default="http://127.0.0.1/studio/callback",
    )
    form = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code.strip(),
        "client_id": cid,
        "redirect_uri": redirect,
    }).encode()
    req = urllib.request.Request(  # noqa: S310
        endpoint,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        return {
            "ok": False,
            "gate_i_complete": False,
            "reason": f"token exchange failed: {exc}",
        }
    token = body.get("access_token") or body.get("id_token") or ""
    validated = validate_bearer(token, verify_signature=True) if token else {
        "ok": False, "reason": "no access_token/id_token in token response",
    }
    return {
        "ok": bool(validated.get("ok")),
        "gate_i_complete": False,
        "token_type": body.get("token_type"),
        "expires_in": body.get("expires_in"),
        "has_access_token": bool(body.get("access_token")),
        "has_id_token": bool(body.get("id_token")),
        "claims": validated.get("claims") if isinstance(validated.get("claims"), dict) else {},
        "signature_verified": bool(validated.get("signature_verified")),
        "reason": (
            "Studio OIDC callback exchanged code + validated JWT; hosted IdP SSO still open"
            if validated.get("ok") else
            (validated.get("reason") or "JWT validation failed after token exchange")
        ),
    }
