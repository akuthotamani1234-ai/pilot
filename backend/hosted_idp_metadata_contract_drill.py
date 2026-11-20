"""Gate I: hosted IdP metadata / discovery contract (not live SSO).

Records required OIDC discovery fields for Studio SSO wiring. Does **not**
perform hosted IdP login — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_idp_metadata_contract_drill.json"

LOCAL_PARTIAL = (
    "loopback_sso_drill.json",
    "loopback_auth_code_sso_drill.json",
    "loopback_pkce_sso_drill.json",
    "studio_oidc_callback_drill.json",
    "hosted_idp_contract_drill.json",
    "hosted_idp_claim_map_completeness_drill.json",
    "studio_sso_login_path_drill.json",
)

REQUIRED_FIELDS = (
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "jwks_uri",
    "response_types_supported",
    "id_token_signing_alg_values_supported",
    "code_challenge_methods_supported",
)


def _linked_metadata() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "hosted_idp_metadata_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_idp_metadata_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "hosted_idp_metadata_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_metadata()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    contract = {
        "discovery_path": "/.well-known/openid-configuration",
        "required_fields": list(REQUIRED_FIELDS),
        "expected_algs": ["RS256"],
        "expected_code_challenge_methods": ["S256"],
        "note": "Metadata contract only; live hosted IdP Studio SSO still required",
    }
    evidence = {
        "gate_i_complete": False,
        "drill": "hosted_idp_metadata_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "contract": contract,
        "live_hosted_sso": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Hosted IdP metadata contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "live hosted IdP Studio SSO still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_metadata()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_metadata()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
