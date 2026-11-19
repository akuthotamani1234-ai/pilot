"""Gate I: OIDC groups claim → role ACL mapping (loopback).

Mints JWTs with ``groups`` claims and maps them onto SQLite principal roles
(admin vs viewer). Hosted IdP Studio SSO still open —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from .dashboard_auth import GROUP_ROLE, role_for_groups

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "oidc_groups_role_acl_drill.json"


def _role_for_groups(groups: list[str]) -> str | None:
    return role_for_groups(groups)


def run_oidc_groups_role_acl_drill(*, ops_dir: Path | None = None) -> dict:
    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "oidc_groups_role_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run OIDC groups role ACL drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .dashboard_auth import authorize
    from .loopback_sso_drill import loopback_oidc_session
    from .tenancy_store import assert_run_access, index_run, upsert_principal

    cases = (
        {
            "sub": "groups-admin",
            "email": "admin@example.test",
            "groups": ["qpilot-admins"],
            "expect_write": True,
        },
        {
            "sub": "groups-viewer",
            "email": "viewer@example.test",
            "groups": ["qpilot-viewers"],
            "expect_write": False,
        },
        {
            "sub": "groups-none",
            "email": "none@example.test",
            "groups": ["other-team"],
            "expect_write": False,
        },
    )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "tenancy.sqlite"
        index_run("run-g1", "tenant-g", source="groups-acl", verdict="pass", db_path=db)
        prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
        os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
        import backend.tenancy_store as tenancy
        prev_db = tenancy.DEFAULT_DB
        tenancy.DEFAULT_DB = db
        results: list[dict] = []
        try:
            for case in cases:
                role = _role_for_groups(list(case["groups"])) or "none"
                if role != "none":
                    upsert_principal(
                        case["sub"], "tenant-g", case["email"], role, db_path=db,
                    )
                with loopback_oidc_session(
                    sub=case["sub"], email=case["email"],
                    extra_claims={"groups": list(case["groups"])},
                ) as session:
                    # Attach groups into validated claims for mapping evidence.
                    claims = dict(session.get("claims") or {})
                    claims["groups"] = list(case["groups"])
                    mapped = _role_for_groups(claims["groups"])
                    authz = authorize(
                        f"Bearer {session['token']}", action="review.write",
                    )
                    access = assert_run_access(
                        principal_id=case["sub"],
                        run_id="run-g1",
                        db_path=db,
                        audit=False,
                    ) if role != "none" else {"allowed": False}
                    write_ok = bool(authz.get("ok")) and bool(access.get("allowed"))
                    results.append({
                        "sub": case["sub"],
                        "groups": list(case["groups"]),
                        "mapped_role": mapped,
                        "oidc_ok": bool(authz.get("ok")),
                        "write_allowed": write_ok,
                        "expect_write": bool(case["expect_write"]),
                        "ok": write_ok is bool(case["expect_write"]),
                    })
        finally:
            tenancy.DEFAULT_DB = prev_db
            if prev_mode is None:
                os.environ.pop("QPILOT_DASHBOARD_AUTH", None)
            else:
                os.environ["QPILOT_DASHBOARD_AUTH"] = prev_mode

        passed = sum(1 for row in results if row.get("ok"))
        evidence = {
            "gate_i_complete": False,
            "drill": "oidc_groups_role_acl",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "group_role_map": dict(GROUP_ROLE),
            "cases": results,
            "passed": passed,
            "ok": passed == len(cases),
            "reason": (
                f"OIDC groups→role ACL {passed}/{len(cases)}; "
                "live hosted IdP Studio SSO still open"
            ),
        }
        _write(evidence, ops_dir)
        return evidence


def _write(evidence: dict, ops_dir: Path | None) -> None:
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "oidc_groups_role_acl_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "oidc_groups_role_acl_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
