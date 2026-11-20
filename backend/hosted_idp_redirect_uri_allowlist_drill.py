"""Gate I: hosted IdP redirect URI allowlist contract (not live SSO).

Records allowed Studio callback redirect URIs for OIDC auth-code flow.
Does **not** perform hosted IdP login — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_idp_redirect_uri_allowlist_drill.json"

LOCAL_PARTIAL = (
    "studio_oidc_callback_drill.json",
    "loopback_auth_code_sso_drill.json",
    "loopback_pkce_sso_drill.json",
    "studio_sso_login_path_drill.json",
    "hosted_idp_metadata_contract_drill.json",
    "hosted_idp_contract_drill.json",
)


def _linked_redirects() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "hosted_idp_redirect_uri_allowlist",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_idp_redirect_uri_allowlist_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "hosted_idp_redirect_uri_allowlist_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_redirects()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    configured = (
        os.environ.get("QPILOT_OIDC_REDIRECT_URI")
        or os.environ.get("OIDC_REDIRECT_URI")
        or "http://127.0.0.1/studio/callback"
    ).strip()
    allowlist = [
        configured,
        "http://127.0.0.1/api/sso/callback",
        "http://localhost/api/sso/callback",
    ]
    # de-dupe preserving order
    seen = set()
    unique = []
    for uri in allowlist:
        if uri and uri not in seen:
            seen.add(uri)
            unique.append(uri)
    evidence = {
        "gate_i_complete": False,
        "drill": "hosted_idp_redirect_uri_allowlist",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "allowlist": unique,
        "configured_redirect_uri": configured,
        "live_hosted_sso": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL) and bool(unique),
        "reason": (
            f"Hosted IdP redirect URI allowlist recorded "
            f"({len(unique)} URIs, {len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "live hosted IdP Studio SSO still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_redirects()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_redirects()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
