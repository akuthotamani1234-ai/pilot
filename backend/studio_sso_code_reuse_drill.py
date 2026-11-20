"""Gate I: Studio SSO authorization-code single use.

Proves a code that already exchanged cannot be presented again. Hosted IdP
Studio SSO still open — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_code_reuse_drill.json"


def _linked_reuse() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "studio_sso_code_reuse",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_studio_sso_code_reuse_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    from .studio_oidc_callback import (
        authorization_code_used,
        exchange_code,
        note_authorization_code_used,
        reset_used_authorization_codes,
    )

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "studio_sso_code_reuse_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_reuse()

    reset_used_authorization_codes()
    code = "studio-code-once"
    fresh = not authorization_code_used(code)
    note_authorization_code_used(code)
    reused = exchange_code(code=code, state="")
    reset_used_authorization_codes()
    rejected = (
        not bool(reused.get("ok"))
        and reused.get("reason") == "authorization code already used"
        and reused.get("code_reused") is True
    )
    ok = fresh and rejected and reused.get("gate_i_complete") is False
    evidence = {
        "gate_i_complete": False,
        "drill": "studio_sso_code_reuse",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "authorization_code_single_use",
        "fresh_code": fresh,
        "reuse_rejected": rejected,
        "reuse_reason": (reused.get("reason") or "")[:160],
        "live_hosted_sso": False,
        "ok": ok,
        "reason": (
            "Studio SSO authorization code is single-use "
            "(second presentation rejected before token exchange); "
            "live hosted IdP Studio SSO still open"
            if ok else
            "Studio SSO authorization-code reuse check incomplete; hosted IdP still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_reuse()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_reuse()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
