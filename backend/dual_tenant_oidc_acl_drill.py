"""Gate I/G: dual-tenant loopback OIDC ACL roundtrip.

Mints JWTs for two principals in different tenants and proves reciprocal
same-tenant allow + cross-tenant deny. Hosted IdP Studio SSO still open —
``gate_i_complete`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "dual_tenant_oidc_acl_drill.json"


def _linked_dual() -> dict:
    return {
        "gate_i_complete": False,
        "gate_g_complete": False,
        "ok": False,
        "drill": "dual_tenant_oidc_acl",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_dual_tenant_oidc_acl_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / "dual_tenant_oidc_acl_drill.json"):
        return _linked_dual()

    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "gate_g_complete": False,
            "drill": "dual_tenant_oidc_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run dual-tenant OIDC ACL drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .dashboard_auth import authorize
    from .loopback_sso_drill import loopback_oidc_session
    from .tenancy_store import assert_run_access, index_run, upsert_principal

    tenants = (
        {"sub": "dual-user-a", "email": "a@example.test", "tenant": "tenant-a", "run": "run-a"},
        {"sub": "dual-user-b", "email": "b@example.test", "tenant": "tenant-b", "run": "run-b"},
    )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "tenancy.sqlite"
        for t in tenants:
            upsert_principal(t["sub"], t["tenant"], t["email"], "admin", db_path=db)
            index_run(t["run"], t["tenant"], source="dual-tenant-acl", verdict="pass", db_path=db)

        prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
        os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
        import backend.tenancy_store as tenancy
        prev_db = tenancy.DEFAULT_DB
        tenancy.DEFAULT_DB = db
        principals: list[dict] = []
        try:
            for t in tenants:
                with loopback_oidc_session(sub=t["sub"], email=t["email"]) as session:
                    authz = authorize(f"Bearer {session['token']}", action="review.write")
                    own = assert_run_access(
                        principal_id=t["sub"], run_id=t["run"], db_path=db, audit=False,
                    )
                    other_run = "run-b" if t["run"] == "run-a" else "run-a"
                    cross = assert_run_access(
                        principal_id=t["sub"], run_id=other_run, db_path=db, audit=False,
                    )
                    principals.append({
                        "sub": t["sub"],
                        "tenant": t["tenant"],
                        "oidc_ok": bool(authz.get("ok")),
                        "signature_verified": bool(authz.get("signature_verified")),
                        "same_tenant_allowed": bool(own.get("allowed")),
                        "cross_tenant_denied": not bool(cross.get("allowed")),
                    })
        finally:
            tenancy.DEFAULT_DB = prev_db
            if prev_mode is None:
                os.environ.pop("QPILOT_DASHBOARD_AUTH", None)
            else:
                os.environ["QPILOT_DASHBOARD_AUTH"] = prev_mode

        ok = all(
            p.get("oidc_ok")
            and p.get("signature_verified")
            and p.get("same_tenant_allowed")
            and p.get("cross_tenant_denied")
            for p in principals
        )
        evidence = {
            "gate_i_complete": False,
            "gate_g_complete": False,
            "drill": "dual_tenant_oidc_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "principals": principals,
            "passed": sum(1 for p in principals if (
                p.get("oidc_ok") and p.get("same_tenant_allowed") and p.get("cross_tenant_denied")
            )),
            "total": len(principals),
            "ok": ok,
            "reason": (
                f"Dual-tenant loopback OIDC ACL {sum(1 for p in principals if p.get('oidc_ok'))}"
                f"/{len(principals)} principals with reciprocal deny; "
                "hosted IdP Studio SSO login still open"
                if ok else
                "Dual-tenant OIDC ACL drill failed; hosted IdP still open"
            ),
        }
    if not _write(evidence, ops_dir):
        return _linked_dual()
    return evidence


def _write(evidence: dict, ops_dir: Path | None) -> bool:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "dual_tenant_oidc_acl_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return False
    dest.mkdir(parents=True, exist_ok=True)
    text = json.dumps(evidence, indent=2)
    if not write_text_unless_linked(dest, name, text):
        return False
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return True
