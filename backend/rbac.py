"""Gate G RBAC: deny-by-default roles inside an optional tenant boundary.

This is an offline authorization helper. It does not replace Studio auth or
wire multi-tenant storage. Unknown roles and missing tenants are refused.
"""
from __future__ import annotations

from uuid import uuid4

ROLES = {
    "viewer": frozenset({"run.read", "report.read"}),
    "operator": frozenset({"run.read", "report.read", "run.write", "review.write"}),
    "admin": frozenset({
        "run.read", "report.read", "run.write", "review.write",
        "tenant.manage", "audit.read",
    }),
}


def allow(*, role: str, action: str, tenant_id: str = "", resource_tenant: str = "") -> dict:
    """Whether ``role`` may perform ``action`` on a resource in ``resource_tenant``."""
    role_key = (role or "").strip().lower()
    act = (action or "").strip().lower()
    perms = ROLES.get(role_key)
    if not perms:
        return {"allowed": False, "reason": "unknown role", "role": role_key, "action": act}
    if act not in perms:
        return {"allowed": False, "reason": "action not permitted for role", "role": role_key, "action": act}
    want = (tenant_id or "").strip()
    own = (resource_tenant or "").strip()
    if want and own and want != own:
        return {"allowed": False, "reason": "tenant isolation", "role": role_key, "action": act,
                "tenant_id": want, "resource_tenant": own}
    return {"allowed": True, "reason": "", "role": role_key, "action": act,
            "tenant_id": want or None}


def audit_event(*, actor: str, action: str, allowed: bool, tenant_id: str = "", detail: str = "") -> dict:
    """Append-friendly audit record (caller persists). No secrets."""
    return {
        "audit_id": uuid4().hex,
        "actor": (actor or "").strip() or "anonymous",
        "action": (action or "").strip().lower(),
        "allowed": bool(allowed),
        "tenant_id": (tenant_id or "").strip() or None,
        "detail": (detail or "").strip()[:500],
    }
