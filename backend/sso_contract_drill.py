"""Gate I: OIDC/hosting env contract snapshot drill.

Records which SSO env vars are present and that JWT helper exists.
Live IdP login still open — gate_i_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .dashboard_sso import snapshot

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "sso_contract_drill.json"


def _linked_sso() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "oidc_hosting_env_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_sso_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "sso_contract_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_sso()

    snap = snapshot()
    evidence = {
        "gate_i_complete": False,
        "drill": "oidc_hosting_env_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "configured": bool(snap.get("configured")),
        "ready": bool(snap.get("ready")),
        "oidc_issuer_env": snap.get("oidc_issuer_env"),
        "oidc_client_env": snap.get("oidc_client_env"),
        "oidc_audience_env": snap.get("oidc_audience_env"),
        "dashboard_host_env": snap.get("dashboard_host_env"),
        "jwt_helper": snap.get("jwt_helper"),
        "ok": snap.get("gate_i_complete") is False and snap.get("ready") is False,
        "reason": snap.get("reason") or (
            "SSO/OIDC contract snapshot recorded; live hosted IdP SSO still open"
        ),
    }

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_sso()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_sso()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
