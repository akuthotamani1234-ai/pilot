"""Gate I: OIDC email domain → tenant ACL binding (loopback).

Maps ``email`` claim domains onto tenants and proves same-tenant allow /
cross-tenant deny. Hosted IdP Studio SSO still open —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "oidc_email_domain_tenant_acl_drill.json"

DOMAIN_TENANT = {
    "acme.test": "tenant-acme",
    "globex.test": "tenant-globex",
}


def _tenant_for_email(email: str) -> str | None:
    if "@" not in (email or ""):
        return None
    domain = email.rsplit("@", 1)[-1].lower()
    return DOMAIN_TENANT.get(domain)


def _linked_domain() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "oidc_email_domain_tenant_acl",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_oidc_email_domain_tenant_acl_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / "oidc_email_domain_tenant_acl_drill.json"):
        return _linked_domain()

    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "oidc_email_domain_tenant_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run OIDC email-domain tenant ACL drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .dashboard_auth import authorize
    from .loopback_sso_drill import loopback_oidc_session
    from .tenancy_store import assert_run_access, index_run, upsert_principal, upsert_tenant

    cases = (
        {"sub": "email-user-a", "email": "alice@acme.test", "run": "run-acme-1"},
        {"sub": "email-user-b", "email": "bob@globex.test", "run": "run-globex-1"},
    )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "tenancy.sqlite"
        for case in cases:
            tid = _tenant_for_email(case["email"])
            assert tid is not None
            upsert_tenant(tid, tid, db_path=db)
            upsert_principal(case["sub"], tid, case["email"], "admin", db_path=db)
            index_run(case["run"], tid, source="email-domain-acl", verdict="pass", db_path=db)

        prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
        os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
        import backend.tenancy_store as tenancy
        prev_db = tenancy.DEFAULT_DB
        tenancy.DEFAULT_DB = db
        results: list[dict] = []
        try:
            for case in cases:
                expected_tid = _tenant_for_email(case["email"])
                with loopback_oidc_session(
                    sub=case["sub"], email=case["email"],
                ) as session:
                    claims = session.get("claims") or {}
                    mapped = _tenant_for_email(str(claims.get("email") or ""))
                    authz = authorize(
                        f"Bearer {session['token']}", action="review.write",
                    )
                    own = assert_run_access(
                        principal_id=case["sub"], run_id=case["run"],
                        db_path=db, audit=False,
                    )
                    other = "run-globex-1" if case["run"] == "run-acme-1" else "run-acme-1"
                    cross = assert_run_access(
                        principal_id=case["sub"], run_id=other,
                        db_path=db, audit=False,
                    )
                    results.append({
                        "sub": case["sub"],
                        "email": case["email"],
                        "mapped_tenant": mapped,
                        "expected_tenant": expected_tid,
                        "domain_match": mapped == expected_tid,
                        "oidc_ok": bool(authz.get("ok")),
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
            r.get("domain_match")
            and r.get("oidc_ok")
            and r.get("same_tenant_allowed")
            and r.get("cross_tenant_denied")
            for r in results
        )
        evidence = {
            "gate_i_complete": False,
            "drill": "oidc_email_domain_tenant_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "domain_map": DOMAIN_TENANT,
            "cases": results,
            "passed": sum(1 for r in results if r.get("domain_match") and r.get("oidc_ok")),
            "ok": ok,
            "reason": (
                f"OIDC email-domain→tenant ACL "
                f"{sum(1 for r in results if r.get('domain_match'))}/{len(results)}; "
                "live hosted IdP Studio SSO still open"
            ),
        }
        if not _write(evidence, ops_dir):
            return _linked_domain()
        return evidence


def _write(evidence: dict, ops_dir: Path | None) -> bool:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "oidc_email_domain_tenant_acl_drill.json"
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
