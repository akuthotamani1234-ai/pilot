"""Gate I: Studio token exchange can require a PKCE code_verifier.

When ``QPILOT_OIDC_PKCE_REQUIRED`` is set, a missing verifier is rejected
before the token endpoint. A present verifier is included on the token form.
Hosted IdP Studio SSO still open — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_pkce_verifier_drill.json"


def _linked_verifier() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "studio_sso_pkce_verifier",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_studio_sso_pkce_verifier_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    from .studio_oidc_callback import exchange_code, token_request_fields

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "studio_sso_pkce_verifier_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_verifier()

    prev = os.environ.get("QPILOT_OIDC_PKCE_REQUIRED")
    os.environ["QPILOT_OIDC_PKCE_REQUIRED"] = "1"
    try:
        missing = exchange_code(code="studio-pkce-code", state="", code_verifier="")
        fields = token_request_fields(
            code="studio-pkce-code",
            client_id="qpilot-studio",
            redirect_uri="http://127.0.0.1/studio/callback",
            code_verifier="verifier-s256",
        )
    finally:
        if prev is None:
            os.environ.pop("QPILOT_OIDC_PKCE_REQUIRED", None)
        else:
            os.environ["QPILOT_OIDC_PKCE_REQUIRED"] = prev
    rejected = (
        missing.get("ok") is False
        and missing.get("pkce_required") is True
        and missing.get("reason") == (
            "code_verifier required when QPILOT_OIDC_PKCE_REQUIRED is set"
        )
    )
    posted = fields.get("code_verifier") == "verifier-s256"
    ok = rejected and posted and missing.get("gate_i_complete") is False
    evidence = {
        "gate_i_complete": False,
        "drill": "studio_sso_pkce_verifier",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "pkce_code_verifier",
        "missing_verifier_rejected": rejected,
        "verifier_on_token_form": posted,
        "live_hosted_sso": False,
        "ok": ok,
        "reason": (
            "Studio SSO PKCE verifier enforced "
            "(missing verifier rejected before token exchange; "
            "present verifier is on the token form); "
            "live hosted IdP Studio SSO still open"
            if ok else
            "Studio SSO PKCE verifier check incomplete; hosted IdP still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_verifier()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_verifier()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
