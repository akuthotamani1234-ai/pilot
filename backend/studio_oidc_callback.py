"""Gate I: Studio OIDC authorization-code callback helper.

Exchanges ``code`` at the configured token endpoint, validates the JWT, and
returns a Studio session-shaped payload. Hosted IdP Studio SSO still open —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request


def _env(*names: str, default: str = "") -> str:
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return default


_USED_CODES: set[str] = set()
_USED_CODES_MAX = 256


def reset_used_authorization_codes() -> None:
    """Clear the process-local single-use authorization-code set."""
    _USED_CODES.clear()


def note_authorization_code_used(code: str) -> None:
    """Remember a code that already produced a valid token exchange."""
    cleaned = (code or "").strip()
    if not cleaned:
        return
    _USED_CODES.add(cleaned)
    while len(_USED_CODES) > _USED_CODES_MAX:
        _USED_CODES.pop()


def authorization_code_used(code: str) -> bool:
    return (code or "").strip() in _USED_CODES


_LOGINS: dict[str, dict] = {}
_LOGIN_MAX = 64
_LOGIN_MAX_AGE_S = 600


def reset_sso_logins() -> None:
    """Clear process-local Studio login attempts."""
    _LOGINS.clear()


def issue_sso_login() -> dict:
    """Start one Studio login. The callback must send this state back once.

    The nonce stays on the server and is compared with the ID token.
    Hosted IdP Studio SSO stays open.
    """
    state = secrets.token_urlsafe(18)
    nonce = secrets.token_urlsafe(18)
    _LOGINS[state] = {"nonce": nonce, "issued_at": time.time()}
    while len(_LOGINS) > _LOGIN_MAX:
        _LOGINS.pop(next(iter(_LOGINS)))
    return {
        "ok": True,
        "gate_i_complete": False,
        "state": state,
        "nonce": nonce,
        "reason": "Studio login started; hosted IdP SSO still open",
    }


def consume_sso_login(state: str, *, now: float | None = None) -> dict:
    """Take a login attempt. A missing, unknown, or expired state is refused."""
    got = (state or "").strip()
    row = _LOGINS.pop(got, None) if got else None
    if not row:
        return {
            "ok": False,
            "gate_i_complete": False,
            "state_ok": False,
            "reason": "SSO login state was not issued",
        }
    issued = row.get("issued_at")
    current = time.time() if now is None else now
    if isinstance(issued, bool) or not isinstance(issued, (int, float)):
        return {
            "ok": False,
            "gate_i_complete": False,
            "state_ok": False,
            "reason": "SSO login state expired",
        }
    if float(current) - float(issued) > _LOGIN_MAX_AGE_S:
        return {
            "ok": False,
            "gate_i_complete": False,
            "state_ok": False,
            "reason": "SSO login state expired",
        }
    return {
        "ok": True,
        "gate_i_complete": False,
        "state": got,
        "nonce": str(row.get("nonce") or ""),
        "state_ok": True,
        "reason": "SSO login state matched the login Studio started",
    }


def pkce_required() -> bool:
    """True when Studio must send a PKCE ``code_verifier`` on the token POST."""
    return _env("QPILOT_OIDC_PKCE_REQUIRED").lower() in {"1", "true", "yes", "on"}


def token_request_fields(
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str = "",
    state: str = "",
) -> dict:
    """Authorization-code token form.

    Includes ``code_verifier`` and the login ``state`` when the caller has them.
    """
    fields = {
        "grant_type": "authorization_code",
        "code": (code or "").strip(),
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    verifier = (code_verifier or "").strip()
    if verifier:
        fields["code_verifier"] = verifier
    posted_state = (state or "").strip()
    if posted_state:
        fields["state"] = posted_state
    return fields


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
    code_verifier: str = "",
    nonce: str = "",
    db_path=None,
) -> dict:
    """POST authorization_code grant; validate access/id token when present."""
    from .oidc_jwt import validate_bearer

    if not (code or "").strip():
        return {
            "ok": False,
            "gate_i_complete": False,
            "reason": "authorization code required",
        }
    if authorization_code_used(code):
        return {
            "ok": False,
            "gate_i_complete": False,
            "code_reused": True,
            "reason": "authorization code already used",
        }

    verifier = (code_verifier or _env("QPILOT_OIDC_CODE_VERIFIER")).strip()
    if pkce_required() and not verifier:
        return {
            "ok": False,
            "gate_i_complete": False,
            "pkce_required": True,
            "reason": "code_verifier required when QPILOT_OIDC_PKCE_REQUIRED is set",
        }

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
    form = urllib.parse.urlencode(token_request_fields(
        code=code,
        client_id=cid,
        redirect_uri=redirect,
        code_verifier=verifier,
        state=state,
    )).encode()
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
    if validated.get("ok"):
        note_authorization_code_used(code)
    started = (nonce or "").strip()
    nonce_check = validate_sso_nonce(
        str(claims.get("nonce") or ""),
        expected=started if started else None,
    )
    if nonce_check.get("nonce_enforced") and not nonce_check.get("ok"):
        return nonce_check
    bound: dict = {}
    if validated.get("ok"):
        from .dashboard_auth import bind_login_principal
        bound = bind_login_principal(claims, db_path=db_path)
    bound_ok = bool(validated.get("ok") and bound.get("principal_bound"))
    if not validated.get("ok"):
        reason = validated.get("reason") or "JWT validation failed after token exchange"
    elif not bound_ok:
        reason = bound.get("reason") or "OIDC token validated but no principal was stored"
    else:
        reason = "Studio OIDC callback exchanged code + validated JWT; hosted IdP SSO still open"
    return {
        "ok": bool(validated.get("ok")),
        "gate_i_complete": False,
        "token_type": body.get("token_type"),
        "expires_in": body.get("expires_in"),
        "has_access_token": bool(body.get("access_token")),
        "has_id_token": bool(body.get("id_token")),
        "access_token": token if bound_ok else "",
        "claims": claims,
        "nonce_enforced": bool(nonce_check.get("nonce_enforced")),
        "nonce_ok": nonce_check.get("nonce_ok"),
        "signature_verified": bool(validated.get("signature_verified")),
        "principal_bound": bool(bound.get("principal_bound")),
        "principal_created": bool(bound.get("created")),
        "role": bound.get("role"),
        "tenant_id": bound.get("tenant_id"),
        "principal_reason": bound.get("reason"),
        "reason": reason,
    }
