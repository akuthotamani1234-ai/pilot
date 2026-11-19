"""Gate I: OIDC org/hd claim → tenant ACL binding (loopback).

Maps ``org`` (or Google-style ``hd``) claims onto tenants and proves
same-tenant allow / cross-tenant deny. Hosted IdP Studio SSO still open —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "oidc_org_tenant_acl_drill.json"

ORG_TENANT = {
    "acme-corp": "tenant-acme",
    "globex-inc": "tenant-globex",
}


def _tenant_for_org(claims: dict) -> str | None:
    org = str(claims.get("org") or claims.get("hd") or "").strip().lower()
    return ORG_TENANT.get(org)


def run_oidc_org_tenant_acl_drill(*, ops_dir: Path | None = None) -> dict:
    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "oidc_org_tenant_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run OIDC org tenant ACL drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .dashboard_auth import authorize
    from .loopback_sso_drill import loopback_oidc_session
    from .tenancy_store import assert_run_access, index_run, upsert_principal, upsert_tenant

    cases = (
        {
            "sub": "org-user-a",
            "email": "a@acme.test",
            "org": "acme-corp",
            "claim_key": "org",
            "run": "run-org-acme",
        },
        {
            "sub": "org-user-b",
            "email": "b@globex.test",
            "org": "globex-inc",
            "claim_key": "hd",
            "run": "run-org-globex",
        },
    )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "tenancy.sqlite"
        for case in cases:
            tid = ORG_TENANT[case["org"]]
            upsert_tenant(tid, tid, db_path=db)
            upsert_principal(case["sub"], tid, case["email"], "admin", db_path=db)
            index_run(case["run"], tid, source="org-acl", verdict="pass", db_path=db)

        prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
        os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
        import backend.tenancy_store as tenancy
        prev_db = tenancy.DEFAULT_DB
        tenancy.DEFAULT_DB = db
        results: list[dict] = []
        try:
            for case in cases:
                extra = {case["claim_key"]: case["org"]}
                with loopback_oidc_session(
                    sub=case["sub"], email=case["email"], extra_claims=extra,
                ) as session:
                    claims = session.get("claims") or {}
                    mapped = _tenant_for_org(claims)
                    expected = ORG_TENANT[case["org"]]
                    authz = authorize(
                        f"Bearer {session['token']}", action="review.write",
                    )
                    own = assert_run_access(
                        principal_id=case["sub"], run_id=case["run"],
                        db_path=db, audit=False,
                    )
                    other = (
                        "run-org-globex"
                        if case["run"] == "run-org-acme"
                        else "run-org-acme"
                    )
                    cross = assert_run_access(
                        principal_id=case["sub"], run_id=other,
                        db_path=db, audit=False,
                    )
                    results.append({
                        "sub": case["sub"],
                        "claim_key": case["claim_key"],
                        "org_claim": claims.get(case["claim_key"]),
                        "mapped_tenant": mapped,
                        "expected_tenant": expected,
                        "org_match": mapped == expected,
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
            r.get("org_match")
            and r.get("oidc_ok")
            and r.get("same_tenant_allowed")
            and r.get("cross_tenant_denied")
            for r in results
        )
        evidence = {
            "gate_i_complete": False,
            "drill": "oidc_org_tenant_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "org_map": ORG_TENANT,
            "cases": results,
            "passed": sum(1 for r in results if r.get("org_match") and r.get("oidc_ok")),
            "ok": ok,
            "reason": (
                f"OIDC org/hd→tenant ACL "
                f"{sum(1 for r in results if r.get('org_match'))}/{len(results)}; "
                "live hosted IdP Studio SSO still open"
            ),
        }
        _write(evidence, ops_dir)
        return evidence


def _write(evidence: dict, ops_dir: Path | None) -> None:
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "oidc_org_tenant_acl_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "oidc_org_tenant_acl_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
