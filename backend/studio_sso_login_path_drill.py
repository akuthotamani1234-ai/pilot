"""Gate I: Studio SSO login-path contract (local wiring, not hosted IdP).

Documents authorize → PKCE → callback → principal → ACL path expected for
Studio SSO. Does **not** perform live hosted IdP login —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_login_path_drill.json"

STEPS = (
    ("discovery", "loopback_sso_drill.json", "OIDC discovery + JWKS"),
    ("authorize_code", "loopback_auth_code_sso_drill.json", "Authorization-code exchange"),
    ("pkce", "loopback_pkce_sso_drill.json", "PKCE S256 challenge"),
    ("callback", "studio_oidc_callback_drill.json", "Studio /api/sso/callback"),
    ("principal", "studio_sso_principal_bootstrap_drill.json", "Principal bootstrap"),
    ("rebind", "studio_sso_session_rebind_drill.json", "Session rebind same sub"),
    ("audience", "studio_sso_audience_binding_drill.json", "Audience binding"),
    ("expiry", "studio_sso_token_expiry_drill.json", "Token expiry rejection"),
    ("state", "studio_sso_state_binding_drill.json", "State binding"),
    ("acl_matrix", "oidc_acl_matrix_pack_drill.json", "Claim ACL matrix"),
    ("claim_map", "hosted_idp_claim_map_completeness_drill.json", "Claim-map completeness"),
    ("idp_pack", "hosted_idp_sso_readiness_pack_drill.json", "IdP SSO readiness pack"),
)


def _linked_path() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "studio_sso_login_path",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_studio_sso_login_path_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "studio_sso_login_path_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_path()

    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for key, artifact, label in STEPS:
        path = ops / artifact
        ready = (not folder_is_linked(path)) and path.is_file()
        rows.append({
            "step": key,
            "artifact": artifact,
            "label": label,
            "ready": ready,
            "hosted_verified": False,
        })
    score = sum(1 for row in rows if row["ready"])
    path = {
        "authorize": "/authorize",
        "token": "/token",
        "callback": "/api/sso/callback",
        "dashboard_auth_mode": "oidc",
        "code_challenge_method": "S256",
        "id_token_alg": "RS256",
    }
    evidence = {
        "gate_i_complete": False,
        "drill": "studio_sso_login_path",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "login_path_contract",
        "path": path,
        "steps": rows,
        "score": score,
        "score_of": len(STEPS),
        "live_hosted_sso": False,
        "ok": score == len(STEPS),
        "reason": (
            f"Studio SSO login-path {score}/{len(STEPS)}; "
            "live hosted IdP Studio SSO still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_path()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_path()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
