"""Gate I: Studio SSO redirect URI allowlist enforcement.

Proves ``validate_redirect_uri`` accepts an allowlisted URI and rejects one
that is not listed. Hosted IdP Studio SSO still open — ``gate_i_complete``
stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = (
    ROOT / "docs" / "ops-evidence"
    / "studio_sso_redirect_allowlist_enforcement_drill.json"
)


def _linked_redirect() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "studio_sso_redirect_allowlist_enforcement",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_studio_sso_redirect_allowlist_enforcement_drill(
    *, ops_dir: Path | None = None,
) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    from .studio_oidc_callback import validate_redirect_uri

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "studio_sso_redirect_allowlist_enforcement_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_redirect()

    allow = "http://127.0.0.1/api/sso/callback,http://localhost/api/sso/callback"
    good = validate_redirect_uri("http://127.0.0.1/api/sso/callback", allowlist=allow)
    bad = validate_redirect_uri("https://evil.example/callback", allowlist=allow)
    unset = validate_redirect_uri("https://evil.example/callback", allowlist="")
    ok = (
        bool(good.get("ok"))
        and bool(good.get("redirect_ok"))
        and not bool(bad.get("ok"))
        and bool(unset.get("ok"))
        and unset.get("redirect_enforced") is False
    )
    evidence = {
        "gate_i_complete": False,
        "drill": "studio_sso_redirect_allowlist_enforcement",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "redirect_allowlist_enforcement",
        "good_ok": bool(good.get("ok")),
        "bad_rejected": not bool(bad.get("ok")),
        "unset_passthrough": bool(unset.get("ok")) and unset.get("redirect_enforced") is False,
        "bad_reason": (bad.get("reason") or "")[:160],
        "live_hosted_sso": False,
        "ok": ok,
        "reason": (
            "Studio SSO redirect allowlist enforcement ok "
            "(listed URI accepted, other URI rejected); "
            "live hosted IdP Studio SSO still open"
            if ok else
            "Studio SSO redirect allowlist enforcement incomplete; hosted IdP still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_redirect()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_redirect()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
