"""Gate I: hosted IdP SSO readiness score (unsigned / not live).

Scores local loopback SSO + ACL evidence against the hosted IdP contract.
Does **not** perform hosted IdP login — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_idp_readiness_drill.json"

CHECKS = (
    ("loopback_sso_drill.json", "Loopback JWKS + RS256 JWT"),
    ("loopback_auth_code_sso_drill.json", "Authorization-code → dashboard oidc"),
    ("loopback_pkce_sso_drill.json", "PKCE S256 authorization-code"),
    ("studio_oidc_callback_drill.json", "Studio /api/sso/callback"),
    ("sso_tenant_acl_drill.json", "OIDC JWT + tenant ACL"),
    ("dual_tenant_oidc_acl_drill.json", "Dual-tenant OIDC ACL"),
    ("oidc_groups_role_acl_drill.json", "OIDC groups→role ACL"),
    ("oidc_tid_tenant_acl_drill.json", "OIDC tid→tenant ACL"),
    ("oidc_email_domain_tenant_acl_drill.json", "OIDC email-domain→tenant ACL"),
    ("oidc_org_tenant_acl_drill.json", "OIDC org/hd→tenant ACL"),
    ("oidc_acl_matrix_pack_drill.json", "OIDC ACL matrix pack"),
    ("hosted_idp_contract_drill.json", "Hosted IdP contract snapshot"),
    ("studio_sso_login_path_drill.json", "Studio SSO login-path contract"),
    ("studio_sso_session_rebind_drill.json", "Studio SSO session rebind"),
    ("studio_sso_audience_binding_drill.json", "Studio SSO audience binding"),
    ("studio_sso_token_expiry_drill.json", "Studio SSO token expiry rejection"),
)


def run_hosted_idp_readiness_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for name, label in CHECKS:
        ready = (ops / name).is_file()
        rows.append({"artifact": name, "label": label, "ready": ready})
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_i_complete": False,
        "drill": "hosted_idp_readiness",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "readiness_score_only",
        "score": score,
        "score_of": len(CHECKS),
        "checks": rows,
        "live_hosted_sso": False,
        "ok": score == len(CHECKS),
        "reason": (
            f"Hosted IdP readiness {score}/{len(CHECKS)}; "
            "live hosted IdP Studio SSO login still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_idp_readiness_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_idp_readiness_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
