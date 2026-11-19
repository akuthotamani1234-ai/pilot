"""Gate I: structural OIDC bearer JWT checks (not live SSO).

Decodes header/payload, checks iss/aud/exp when env is configured.
Signature verification requires the optional ``PyJWT`` package + JWKS fetch.
Never marks Gate I complete.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


def _b64url_json(segment: str) -> dict:
    pad = "=" * (-len(segment) % 4)
    raw = base64.urlsafe_b64decode(segment + pad)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JWT segment is not a JSON object")
    return data


def _env(*names: str) -> str:
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return ""


_SEEN_JTI: set[str] = set()
_SEEN_JTI_MAX = 256


def replay_jti_enabled() -> bool:
    return (os.getenv("QPILOT_SSO_REPLAY_JTI") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def reset_seen_jti() -> None:
    """Clear the process-local jti replay cache (tests and drills)."""
    _SEEN_JTI.clear()


def _jti_already_seen(jti: str) -> bool:
    if jti in _SEEN_JTI:
        return True
    _SEEN_JTI.add(jti)
    if len(_SEEN_JTI) > _SEEN_JTI_MAX:
        _SEEN_JTI.pop()
    return False


def configured_claims() -> dict:
    return {
        "issuer": _env("QPILOT_OIDC_ISSUER", "BLOWAI_OIDC_ISSUER", "OIDC_ISSUER"),
        "audience": _env("QPILOT_OIDC_AUDIENCE", "BLOWAI_OIDC_AUDIENCE", "OIDC_AUDIENCE"),
        "client_id": _env("QPILOT_OIDC_CLIENT_ID", "BLOWAI_OIDC_CLIENT_ID", "OIDC_CLIENT_ID"),
    }


def decode_unverified(token: str) -> dict:
    """Split and decode a compact JWT without verifying the signature."""
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        raise ValueError("token is not a compact JWT (header.payload.signature)")
    return {"header": _b64url_json(parts[0]), "payload": _b64url_json(parts[1]), "parts": parts}


def _fetch_jwks(issuer: str) -> dict:
    parsed = urlparse(issuer if issuer.endswith("/") else issuer + "/")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("OIDC issuer must be http(s)")
    # Standard OIDC discovery → jwks_uri, with a common fallback path.
    discovery = issuer.rstrip("/") + "/.well-known/openid-configuration"
    req = urllib.request.Request(discovery, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            meta = json.loads(resp.read().decode("utf-8"))
        jwks_uri = str(meta.get("jwks_uri") or "")
    except Exception:
        jwks_uri = issuer.rstrip("/") + "/.well-known/jwks.json"
    if urlparse(jwks_uri).scheme not in {"http", "https"}:
        raise ValueError("jwks_uri must be http(s)")
    req = urllib.request.Request(jwks_uri, method="GET")  # noqa: S310
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def validate_bearer(token: str, *, verify_signature: bool = True) -> dict:
    """Validate bearer JWT structure + configured iss/aud/exp.

    Returns ``{ok, reason, gate_i_complete: False, ...}``. When signature
    verification is requested, a missing issuer, a missing verifier, or a
    failed signature check is refused. Hosted IdP SSO stays open.
    """
    cfg = configured_claims()
    out = {
        "ok": False,
        "gate_i_complete": False,
        "ready": False,
        "reason": "",
        "claims": {},
        "signature_verified": False,
    }
    try:
        decoded = decode_unverified(token)
    except Exception as exc:
        out["reason"] = f"JWT decode failed: {exc}"
        return out
    payload = decoded["payload"]
    out["claims"] = {
        "iss": payload.get("iss"),
        "aud": payload.get("aud"),
        "sub": payload.get("sub"),
        "exp": payload.get("exp"),
        "email": payload.get("email"),
        "tid": payload.get("tid"),
        "nonce": payload.get("nonce"),
        "jti": payload.get("jti"),
        "nbf": payload.get("nbf"),
    }
    if "groups" in payload:
        out["claims"]["groups"] = payload.get("groups")
    if cfg["issuer"] and str(payload.get("iss") or "") != cfg["issuer"]:
        out["reason"] = f"iss mismatch (want {cfg['issuer']})"
        return out
    if cfg["audience"]:
        aud = payload.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if cfg["audience"] not in {str(a) for a in audiences if a is not None}:
            out["reason"] = f"aud mismatch (want {cfg['audience']})"
            return out
    exp = payload.get("exp")
    if exp is not None:
        try:
            if float(exp) < time.time():
                out["reason"] = "token expired"
                return out
        except (TypeError, ValueError):
            out["reason"] = "exp claim is not a number"
            return out
    nbf = payload.get("nbf")
    if nbf is not None:
        try:
            # 30s leeway absorbs small clock skew without accepting a future token.
            if float(nbf) > time.time() + 30:
                out["reason"] = "token not yet valid"
                return out
        except (TypeError, ValueError):
            out["reason"] = "nbf claim is not a number"
            return out

    if replay_jti_enabled():
        jti = str(payload.get("jti") or "").strip()
        if not jti:
            out["reason"] = "jti required when QPILOT_SSO_REPLAY_JTI is set"
            return out
        if _jti_already_seen(jti):
            out["reason"] = "jti replay rejected"
            return out

    if verify_signature and not cfg["issuer"]:
        out["reason"] = (
            "QPILOT_OIDC_ISSUER is required before a signature can be checked; "
            "live SSO still open"
        )
        return out

    if verify_signature and cfg["issuer"]:
        try:
            import jwt  # PyJWT optional
            from jwt import PyJWKClient

            jwks = _fetch_jwks(cfg["issuer"])
            # PyJWKClient wants a URI; use discovery jwks via temp inline keys when needed.
            jwks_uri = cfg["issuer"].rstrip("/") + "/.well-known/jwks.json"
            try:
                client = PyJWKClient(jwks_uri)
                key = client.get_signing_key_from_jwt(token).key
            except Exception:
                # Fall back: first RSA key in fetched JWKS document via jwt algorithms.
                keys = jwks.get("keys") if isinstance(jwks, dict) else None
                if not keys:
                    raise RuntimeError("JWKS has no keys") from None
                key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(keys[0]))
            jwt.decode(
                token,
                key=key,
                algorithms=[decoded["header"].get("alg") or "RS256"],
                audience=cfg["audience"] or None,
                issuer=cfg["issuer"],
                options={"verify_aud": bool(cfg["audience"])},
            )
            out["signature_verified"] = True
        except ImportError:
            out["reason"] = (
                "PyJWT is not installed, so the signature was not verified; "
                "live SSO still open"
            )
            return out
        except (urllib.error.URLError, TimeoutError, ValueError, Exception) as exc:
            out["reason"] = (
                f"signature verification failed: {exc}; live SSO still open"
            )
            return out

    out["ok"] = True
    out["reason"] = (
        "JWT claims (+ signature) accepted structurally; live hosted SSO login still open"
        if out["signature_verified"] else
        "JWT claims accepted structurally; signature not verified; live SSO still open"
    )
    return out
