"""Gate I: OIDC ``tid`` claim → tenant ACL binding (loopback).

Mints JWTs with ``tid`` claims and binds principals to that tenant for
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
EVIDENCE = ROOT / "docs" / "ops-evidence" / "oidc_tid_tenant_acl_drill.json"


def run_oidc_tid_tenant_acl_drill(*, ops_dir: Path | None = None) -> dict:
    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "oidc_tid_tenant_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run OIDC tid tenant ACL drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .dashboard_auth import authorize
    from .loopback_sso_drill import loopback_oidc_session
    from .tenancy_store import assert_run_access, index_run, upsert_principal

    cases = (
        {"sub": "tid-user-a", "email": "a@example.test", "tid": "tenant-tid-a", "run": "run-tid-a"},
        {"sub": "tid-user-b", "email": "b@example.test", "tid": "tenant-tid-b", "run": "run-tid-b"},
    )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "tenancy.sqlite"
        for case in cases:
            upsert_principal(case["sub"], case["tid"], case["email"], "admin", db_path=db)
            index_run(case["run"], case["tid"], source="tid-acl", verdict="pass", db_path=db)

        prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
        os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
        import backend.tenancy_store as tenancy
        prev_db = tenancy.DEFAULT_DB
        tenancy.DEFAULT_DB = db
        results: list[dict] = []
        try:
            for case in cases:
                with loopback_oidc_session(
                    sub=case["sub"],
                    email=case["email"],
                    extra_claims={"tid": case["tid"]},
                ) as session:
                    claims = session.get("claims") or {}
                    authz = authorize(
                        f"Bearer {session['token']}", action="review.write",
                    )
                    own = assert_run_access(
                        principal_id=case["sub"], run_id=case["run"], db_path=db, audit=False,
                    )
                    other = "run-tid-b" if case["run"] == "run-tid-a" else "run-tid-a"
                    cross = assert_run_access(
                        principal_id=case["sub"], run_id=other, db_path=db, audit=False,
                    )
                    results.append({
                        "sub": case["sub"],
                        "tid_claim": claims.get("tid"),
                        "tid_expected": case["tid"],
                        "tid_match": claims.get("tid") == case["tid"],
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
            r.get("tid_match")
            and r.get("oidc_ok")
            and r.get("same_tenant_allowed")
            and r.get("cross_tenant_denied")
            for r in results
        )
        evidence = {
            "gate_i_complete": False,
            "drill": "oidc_tid_tenant_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cases": results,
            "passed": sum(1 for r in results if r.get("tid_match") and r.get("oidc_ok")),
            "ok": ok,
            "reason": (
                f"OIDC tid→tenant ACL {sum(1 for r in results if r.get('tid_match'))}/"
                f"{len(results)}; live hosted IdP Studio SSO still open"
            ),
        }
        _write(evidence, ops_dir)
        return evidence


def _write(evidence: dict, ops_dir: Path | None) -> None:
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "oidc_tid_tenant_acl_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "oidc_tid_tenant_acl_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
