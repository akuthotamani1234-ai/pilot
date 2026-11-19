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


def validate_sso_state(state: str, *, expected: str | None = None) -> dict:
    """Reject callback ``state`` when an expected value is configured.

    When ``QPILOT_SSO_EXPECTED_STATE`` (or ``expected``) is empty, state is not
    enforced — hosted IdP Studio SSO still open.
    """
    want = (expected if expected is not None else _env("QPILOT_SSO_EXPECTED_STATE")).strip()
    got = (state or "").strip()
    if not want:
        return {
            "ok": True,
            "gate_i_complete": False,
            "state_enforced": False,
            "reason": "SSO state not enforced (expected state unset)",
        }
    if got != want:
        return {
            "ok": False,
            "gate_i_complete": False,
            "state_enforced": True,
            "state_ok": False,
            "reason": "state mismatch",
        }
    return {
        "ok": True,
        "gate_i_complete": False,
        "state_enforced": True,
        "state_ok": True,
        "reason": "SSO state matched expected value",
    }


def validate_sso_nonce(nonce: str, *, expected: str | None = None) -> dict:
    """Reject an ID-token ``nonce`` when an expected value is configured.

    When ``QPILOT_SSO_EXPECTED_NONCE`` (or ``expected``) is empty, nonce is not
    enforced — hosted IdP Studio SSO still open.
    """
    want = (expected if expected is not None else _env("QPILOT_SSO_EXPECTED_NONCE")).strip()
    got = (nonce or "").strip()
    if not want:
        return {
            "ok": True,
            "gate_i_complete": False,
            "nonce_enforced": False,
            "reason": "SSO nonce not enforced (expected nonce unset)",
        }
    if got != want:
        return {
            "ok": False,
            "gate_i_complete": False,
            "nonce_enforced": True,
            "nonce_ok": False,
            "reason": "nonce mismatch",
        }
    return {
        "ok": True,
        "gate_i_complete": False,
        "nonce_enforced": True,
        "nonce_ok": True,
        "reason": "SSO nonce matched expected value",
    }


def validate_redirect_uri(redirect_uri: str, *, allowlist: str | None = None) -> dict:
    """Reject a callback redirect URI that is not on the configured allowlist.

    When ``QPILOT_OIDC_REDIRECT_ALLOWLIST`` (comma-separated) is empty, the
    check is not enforced — hosted IdP Studio SSO still open.
    """
    raw = allowlist if allowlist is not None else _env("QPILOT_OIDC_REDIRECT_ALLOWLIST")
    allowed = [part.strip() for part in raw.split(",") if part.strip()]
    got = (redirect_uri or "").strip()
    if not allowed:
        return {
            "ok": True,
            "gate_i_complete": False,
            "redirect_enforced": False,
            "reason": "SSO redirect URI allowlist not enforced (unset)",
        }
    if got not in allowed:
        return {
            "ok": False,
            "gate_i_complete": False,
            "redirect_enforced": True,
            "redirect_ok": False,
            "reason": "redirect_uri not allowlisted",
        }
    return {
        "ok": True,
        "gate_i_complete": False,
        "redirect_enforced": True,
        "redirect_ok": True,
        "reason": "SSO redirect URI is allowlisted",
    }


def exchange_code(
    *,
    code: str,
    redirect_uri: str | None = None,
    client_id: str | None = None,
    state: str = "",
) -> dict:
    """POST authorization_code grant; validate access/id token when present."""
    from .oidc_jwt import validate_bearer

    state_check = validate_sso_state(state)
    if state_check.get("state_enforced") and not state_check.get("ok"):
        return state_check

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
    redirect_check = validate_redirect_uri(redirect)
    if redirect_check.get("redirect_enforced") and not redirect_check.get("ok"):
        return redirect_check
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
    token = body.get("id_token") or body.get("access_token") or ""
    validated = validate_bearer(token, verify_signature=True) if token else {
        "ok": False, "reason": "no access_token/id_token in token response",
    }
    claims = validated.get("claims") if isinstance(validated.get("claims"), dict) else {}
    nonce_check = validate_sso_nonce(str(claims.get("nonce") or ""))
    if nonce_check.get("nonce_enforced") and not nonce_check.get("ok"):
        return nonce_check
    return {
        "ok": bool(validated.get("ok")),
        "gate_i_complete": False,
        "token_type": body.get("token_type"),
        "expires_in": body.get("expires_in"),
        "has_access_token": bool(body.get("access_token")),
        "has_id_token": bool(body.get("id_token")),
        "claims": claims,
        "nonce_enforced": bool(nonce_check.get("nonce_enforced")),
        "nonce_ok": nonce_check.get("nonce_ok"),
        "signature_verified": bool(validated.get("signature_verified")),
        "reason": (
            "Studio OIDC callback exchanged code + validated JWT; hosted IdP SSO still open"
            if validated.get("ok") else
            (validated.get("reason") or "JWT validation failed after token exchange")
        ),
    }
