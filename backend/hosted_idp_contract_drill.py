"""Gate I: hosted IdP Studio SSO contract snapshot (not executed against live IdP).

Records required OIDC endpoints, PKCE, claim mapping, and Studio callback
wiring expected of a production IdP. Does **not** perform hosted SSO login —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_idp_contract_drill.json"

LOCAL_PARTIAL = (
    "loopback_sso_drill.json",
    "loopback_auth_code_sso_drill.json",
    "loopback_pkce_sso_drill.json",
    "studio_oidc_callback_drill.json",
    "sso_tenant_acl_drill.json",
)


def run_hosted_idp_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    contract = {
        "discovery": "/.well-known/openid-configuration",
        "jwks": "/.well-known/jwks.json",
        "authorize": "/authorize",
        "token": "/token",
        "response_type": "code",
        "code_challenge_method": "S256",
        "id_token_alg": "RS256",
        "required_claims": ["iss", "aud", "sub", "exp", "iat"],
        "optional_claims": ["email", "tid", "groups"],
        "studio_callback": "/api/sso/callback",
        "dashboard_auth_mode": "oidc",
        "tenant_acl": "SQLite/Postgres principal scoping required",
    }
    evidence = {
        "gate_i_complete": False,
        "drill": "hosted_idp_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "contract": contract,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Hosted IdP SSO contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials present); "
            "live hosted IdP Studio SSO login still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "hosted_idp_contract_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_idp_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
