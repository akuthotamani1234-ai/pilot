"""Gate I: Studio SSO principal bootstrap from OIDC claims (loopback).

On first login, upserts a principal from ``sub``/``email``/``tid`` claims and
proves tenant ACL. Hosted IdP Studio SSO still open —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_principal_bootstrap_drill.json"


def run_studio_sso_principal_bootstrap_drill(*, ops_dir: Path | None = None) -> dict:
    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "studio_sso_principal_bootstrap",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run SSO principal bootstrap drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .dashboard_auth import authorize
    from .loopback_sso_drill import loopback_oidc_session
    from .tenancy_store import (
        assert_run_access,
        get_principal,
        index_run,
        upsert_principal,
        upsert_tenant,
    )

    sub = "bootstrap-user-1"
    email = "bootstrap@example.test"
    tid = "tenant-bootstrap"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "tenancy.sqlite"
        before = get_principal(sub, db_path=db)
        upsert_tenant(tid, "Bootstrap Tenant", db_path=db)
        index_run("run-boot-1", tid, source="sso-bootstrap", verdict="pass", db_path=db)

        prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
        os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
        import backend.tenancy_store as tenancy
        prev_db = tenancy.DEFAULT_DB
        tenancy.DEFAULT_DB = db
        try:
            with loopback_oidc_session(
                sub=sub, email=email, extra_claims={"tid": tid},
            ) as session:
                claims = session.get("claims") or {}
                # First-login bootstrap: create principal from claims.
                created = upsert_principal(
                    str(claims.get("sub") or sub),
                    str(claims.get("tid") or tid),
                    str(claims.get("email") or email),
                    "admin",
                    db_path=db,
                )
                after = get_principal(sub, db_path=db)
                authz = authorize(
                    f"Bearer {session['token']}", action="review.write",
                )
                own = assert_run_access(
                    principal_id=sub, run_id="run-boot-1", db_path=db, audit=False,
                )
                ok = (
                    before is None
                    and after is not None
                    and after.get("tenant_id") == tid
                    and after.get("email") == email
                    and bool(authz.get("ok"))
                    and bool(own.get("allowed"))
                    and created.get("principal_id") == sub
                )
                evidence = {
                    "gate_i_complete": False,
                    "drill": "studio_sso_principal_bootstrap",
                    "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "bootstrapped": {
                        "principal_id": sub,
                        "tenant_id": tid,
                        "email": email,
                        "was_missing": before is None,
                        "present_after": after is not None,
                    },
                    "oidc_ok": bool(authz.get("ok")),
                    "same_tenant_allowed": bool(own.get("allowed")),
                    "ok": ok,
                    "reason": (
                        "Studio SSO principal bootstrap from OIDC claims ok; "
                        "live hosted IdP Studio SSO still open"
                        if ok else
                        "Studio SSO principal bootstrap failed; hosted IdP still open"
                    ),
                }
        finally:
            tenancy.DEFAULT_DB = prev_db
            if prev_mode is None:
                os.environ.pop("QPILOT_DASHBOARD_AUTH", None)
            else:
                os.environ["QPILOT_DASHBOARD_AUTH"] = prev_mode

        _write(evidence, ops_dir)
        return evidence


def _write(evidence: dict, ops_dir: Path | None) -> None:
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "studio_sso_principal_bootstrap_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "studio_sso_principal_bootstrap_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
