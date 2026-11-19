"""Gate I: Studio SSO session rebind (same sub → same principal, loopback).

Proves a second login with the same ``sub`` reuses the principal instead of
creating a duplicate. Hosted IdP Studio SSO still open —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_session_rebind_drill.json"


def run_studio_sso_session_rebind_drill(*, ops_dir: Path | None = None) -> dict:
    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "studio_sso_session_rebind",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run SSO session rebind drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .loopback_sso_drill import loopback_oidc_session
    from .tenancy_store import get_principal, upsert_principal, upsert_tenant

    sub = "rebind-user-1"
    email = "rebind@example.test"
    tid = "tenant-rebind"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "tenancy.sqlite"
        upsert_tenant(tid, "Rebind Tenant", db_path=db)
        prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
        os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
        try:
            with loopback_oidc_session(
                sub=sub, email=email, extra_claims={"tid": tid},
            ) as session1:
                first = upsert_principal(sub, tid, email, "viewer", db_path=db)
                token1 = session1.get("token")
            with loopback_oidc_session(
                sub=sub, email=email, extra_claims={"tid": tid},
            ) as session2:
                second = upsert_principal(sub, tid, email, "viewer", db_path=db)
                token2 = session2.get("token")
            after = get_principal(sub, db_path=db)
        finally:
            if prev_mode is None:
                os.environ.pop("QPILOT_DASHBOARD_AUTH", None)
            else:
                os.environ["QPILOT_DASHBOARD_AUTH"] = prev_mode

        ok = (
            first.get("principal_id") == sub
            and second.get("principal_id") == sub
            and after is not None
            and after.get("principal_id") == sub
            and bool(token1)
            and bool(token2)
            and token1 != token2
        )
        evidence = {
            "gate_i_complete": False,
            "drill": "studio_sso_session_rebind",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kind": "loopback_rebind",
            "principal_id": sub,
            "tenant_id": tid,
            "first_ok": first.get("principal_id") == sub,
            "second_ok": second.get("principal_id") == sub,
            "tokens_distinct": bool(token1) and bool(token2) and token1 != token2,
            "live_hosted_sso": False,
            "ok": ok,
            "reason": (
                "Studio SSO session rebind ok (same sub → same principal); "
                "live hosted IdP Studio SSO still open"
                if ok else
                "Studio SSO session rebind incomplete; hosted IdP still open"
            ),
        }
        _write(evidence, ops_dir)
        return evidence


def _write(evidence: dict, ops_dir: Path | None) -> None:
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "studio_sso_session_rebind_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "studio_sso_session_rebind_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
