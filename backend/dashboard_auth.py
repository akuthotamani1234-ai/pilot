"""Gate I: pluggable dashboard auth for approvals (not full SSO).

Modes via QPILOT_DASHBOARD_AUTH / BLOWAI_DASHBOARD_AUTH:
  none      — open on localhost (default when no token)
  bearer    — Authorization: Bearer <QPILOT_DASHBOARD_TOKEN>
  webhook   — X-QA-Token / Bearer matching WEBHOOK_TOKEN or dashboard token
  principal — Bearer principal_id resolved via tenancy_store + rbac.allow(review.write)
  oidc      — Bearer JWT validated via oidc_jwt (iss/aud/exp; live IdP SSO still open)

Hosting and real IdP SSO remain open. gate_i_complete stays False.
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


def auth_mode() -> str:
    raw = (
        os.getenv("QPILOT_DASHBOARD_AUTH")
        or os.getenv("BLOWAI_DASHBOARD_AUTH")
        or ""
    ).strip().lower()
    if raw in {"none", "bearer", "webhook", "principal", "oidc"}:
        return raw
    if configured_token():
        return "bearer"
    if (os.getenv("WEBHOOK_TOKEN") or "").strip():
        return "webhook"
    return "none"


def required() -> bool:
    return auth_mode() != "none"


def _extract_bearer(authorization: str | None) -> str:
    given = (authorization or "").strip()
    if given.lower().startswith("bearer "):
        return given[7:].strip()
    return given


def _oidc_principal(claims: dict, *, action: str, mode: str, verdict: dict) -> dict:
    """A valid JWT is not enough. The subject must be a principal whose role allows the action."""
    sub = str(claims.get("sub") or "").strip()
    base = {
        "required": True,
        "mode": mode,
        "claims": claims,
        "signature_verified": bool(verdict.get("signature_verified")),
        "gate_i_complete": False,
        "principal_id": sub,
    }
    if not sub:
        return {**base, "ok": False, "reason": "OIDC token has no subject"}
    try:
        from .rbac import allow
        from .tenancy_store import get_principal
        row = get_principal(sub)
    except Exception as exc:
        return {**base, "ok": False, "reason": f"principal auth failed: {exc}"}
    if row is None:
        return {**base, "ok": False, "reason": "unknown principal"}
    tid = str(claims.get("tid") or "").strip()
    if tid and tid != str(row.get("tenant_id") or ""):
        return {
            **base,
            "ok": False,
            "reason": "token tenant does not match principal",
            "tenant_id": row.get("tenant_id"),
        }
    decision = allow(
        role=row["role"], action=action,
        tenant_id=row["tenant_id"], resource_tenant=row["tenant_id"],
    )
    if not decision.get("allowed"):
        return {
            **base,
            "ok": False,
            "reason": decision.get("reason") or "RBAC denied",
            "role": row["role"],
            "tenant_id": row["tenant_id"],
        }
    return {
        **base,
        "ok": True,
        "reason": "OIDC principal RBAC accepted (live hosted SSO still open)",
        "role": row["role"],
        "tenant_id": row["tenant_id"],
    }


def authorize(authorization: str | None, *, x_qa_token: str | None = None,
              action: str = "review.write") -> dict:
    """Return {ok, reason, mode, principal?}."""
    mode = auth_mode()
    if mode == "none":
        return {
            "ok": True,
            "required": False,
            "mode": mode,
            "reason": "dashboard auth unset; localhost Studio allows open access",
        }

    bearer = _extract_bearer(authorization)
    if mode == "bearer":
        expected = configured_token()
        if expected and bearer and hmac.compare_digest(bearer, expected):
            return {"ok": True, "required": True, "mode": mode, "reason": "bearer token accepted"}
        return {
            "ok": False,
            "required": True,
            "mode": mode,
            "reason": "Authorization Bearer token required for dashboard approvals",
        }

    if mode == "webhook":
        expected = configured_token() or (os.getenv("WEBHOOK_TOKEN") or "").strip()
        candidate = (x_qa_token or "").strip() or bearer
        if expected and candidate and hmac.compare_digest(candidate, expected):
            return {"ok": True, "required": True, "mode": mode, "reason": "webhook/shared token accepted"}
        return {
            "ok": False,
            "required": True,
            "mode": mode,
            "reason": "X-QA-Token or Bearer matching WEBHOOK_TOKEN/QPILOT_DASHBOARD_TOKEN required",
        }

    if mode == "oidc":
        from .oidc_jwt import validate_bearer
        if not bearer:
            return {
                "ok": False,
                "required": True,
                "mode": mode,
                "reason": "Authorization Bearer <jwt> required for OIDC dashboard auth",
            }
        verdict = validate_bearer(bearer, verify_signature=True)
        claims = verdict.get("claims") or {}
        if not verdict.get("ok"):
            return {
                "ok": False,
                "required": True,
                "mode": mode,
                "reason": verdict.get("reason") or "OIDC JWT rejected",
                "claims": claims,
                "gate_i_complete": False,
            }
        return _oidc_principal(claims, action=action, mode=mode, verdict=verdict)

    if mode != "principal":
        return {
            "ok": False,
            "required": True,
            "mode": mode,
            "reason": f"unsupported dashboard auth mode: {mode}",
        }

    # principal mode
    principal_id = bearer
    if not principal_id:
        return {
            "ok": False,
            "required": True,
            "mode": mode,
            "reason": "Authorization Bearer <principal_id> required",
        }
    try:
        from .rbac import allow
        from .tenancy_store import get_principal
        row = get_principal(principal_id)
        if row is None:
            return {
                "ok": False,
                "required": True,
                "mode": mode,
                "reason": "unknown principal",
                "principal_id": principal_id,
            }
        verdict = allow(role=row["role"], action=action, tenant_id=row["tenant_id"],
                        resource_tenant=row["tenant_id"])
        if not verdict.get("allowed"):
            return {
                "ok": False,
                "required": True,
                "mode": mode,
                "reason": verdict.get("reason") or "RBAC denied",
                "principal_id": principal_id,
                "role": row["role"],
            }
        return {
            "ok": True,
            "required": True,
            "mode": mode,
            "reason": "principal RBAC accepted",
            "principal_id": principal_id,
            "tenant_id": row["tenant_id"],
            "role": row["role"],
        }
    except Exception as exc:
        return {
            "ok": False,
            "required": True,
            "mode": mode,
            "reason": f"principal auth failed: {exc}",
        }


def snapshot() -> dict:
    mode = auth_mode()
    return {
        "gate_i_complete": False,
        "mode": mode,
        "token_configured": bool(configured_token()),
        "reason": (
            f"Dashboard auth mode={mode}; SSO/hosting still open"
            if mode != "none" else
            "Dashboard auth unset; approvals open on localhost only"
        ),
    }
