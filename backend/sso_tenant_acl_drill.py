"""Gate I/G: loopback OIDC JWT → tenant ACL drill.

While a loopback JWKS is live, authorize via dashboard ``oidc`` mode and prove
same-tenant allow + cross-tenant deny in SQLite tenancy. Hosted IdP Studio SSO
still open — ``gate_i_complete`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "sso_tenant_acl_drill.json"


def _linked_acl() -> dict:
    return {
        "gate_i_complete": False,
        "gate_g_complete": False,
        "ok": False,
        "drill": "sso_tenant_acl",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_sso_tenant_acl_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "sso_tenant_acl_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_acl()

    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "gate_g_complete": False,
            "drill": "sso_tenant_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run SSO tenant ACL drill",
        }
    else:
        from .dashboard_auth import authorize
        from .loopback_sso_drill import loopback_oidc_session
        from .tenancy_store import assert_run_access, index_run, upsert_principal

        sub = "loopback-user-1"
        email = "loopback@example.test"
        # ignore_cleanup_errors: Windows can keep SQLite WAL handles briefly open.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = Path(tmp) / "tenancy.sqlite"
            try:
                upsert_principal(sub, "tenant-a", email, "admin", db_path=db)
                upsert_principal("other-user", "tenant-b", "b@example.test", "admin", db_path=db)
                index_run("run-a", "tenant-a", source="sso-acl-drill", verdict="pass", db_path=db)
                index_run("run-b", "tenant-b", source="sso-acl-drill", verdict="pass", db_path=db)

                allow = assert_run_access(principal_id=sub, run_id="run-a", db_path=db, audit=False)
                deny = assert_run_access(principal_id=sub, run_id="run-b", db_path=db, audit=False)

                prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
                os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
                import backend.tenancy_store as tenancy
                prev_db = tenancy.DEFAULT_DB
                tenancy.DEFAULT_DB = db
                try:
                    with loopback_oidc_session(sub=sub, email=email) as session:
                        authz = authorize(f"Bearer {session['token']}", action="review.write")
                        result = session["validate"]
                finally:
                    tenancy.DEFAULT_DB = prev_db
                    if prev_mode is None:
                        os.environ.pop("QPILOT_DASHBOARD_AUTH", None)
                    else:
                        os.environ["QPILOT_DASHBOARD_AUTH"] = prev_mode

                evidence = {
                    "gate_i_complete": False,
                    "gate_g_complete": False,
                    "drill": "sso_tenant_acl",
                    "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "principal_id": sub,
                    "email": email,
                    "oidc_authorize": {
                        "ok": bool(authz.get("ok")),
                        "mode": authz.get("mode"),
                        "signature_verified": bool(authz.get("signature_verified")),
                        "reason": authz.get("reason"),
                    },
                    "acl": {
                        "same_tenant_allowed": bool(allow.get("allowed")),
                        "cross_tenant_denied": not bool(deny.get("allowed")),
                        "allow": {k: allow.get(k) for k in ("allowed", "reason", "tenant_id")},
                        "deny": {k: deny.get(k) for k in ("allowed", "reason", "tenant_id")},
                    },
                    "signature_verified": bool(result.get("signature_verified")),
                    "ok": (
                        bool(authz.get("ok"))
                        and bool(authz.get("signature_verified") or result.get("signature_verified"))
                        and bool(allow.get("allowed"))
                        and not bool(deny.get("allowed"))
                    ),
                    "reason": (
                        "Loopback OIDC JWT authorized + SQLite tenant ACL "
                        "(same allow / cross deny); hosted IdP Studio SSO still open"
                    ),
                }
            finally:
                # Drop SQLite file handles before TemporaryDirectory cleanup (WinError 32).
                import gc
                gc.collect()

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_acl()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_acl()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
