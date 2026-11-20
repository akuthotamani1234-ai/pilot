"""Gate I: Studio SSO token expiry rejection (loopback).

Proves an expired JWT is rejected while a fresh token validates. Hosted IdP
Studio SSO still open — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_token_expiry_drill.json"


def _linked_expiry() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "studio_sso_token_expiry",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_studio_sso_token_expiry_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / "studio_sso_token_expiry_drill.json"):
        return _linked_expiry()

    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "studio_sso_token_expiry",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run SSO token expiry drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .loopback_sso_drill import loopback_oidc_session

    prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
    os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
    try:
        with loopback_oidc_session(exp_offset_seconds=600) as fresh:
            fresh_result = dict(fresh["validate"] or {})
        with loopback_oidc_session(exp_offset_seconds=-120) as expired:
            expired_result = dict(expired["validate"] or {})
    finally:
        if prev_mode is None:
            os.environ.pop("QPILOT_DASHBOARD_AUTH", None)
        else:
            os.environ["QPILOT_DASHBOARD_AUTH"] = prev_mode

    fresh_ok = bool(fresh_result.get("ok")) and bool(fresh_result.get("signature_verified"))
    expired_rejected = not bool(expired_result.get("ok"))
    ok = fresh_ok and expired_rejected
    evidence = {
        "gate_i_complete": False,
        "drill": "studio_sso_token_expiry",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "loopback_token_expiry",
        "fresh_ok": fresh_ok,
        "expired_rejected": expired_rejected,
        "expired_reason": (expired_result.get("reason") or "")[:160],
        "live_hosted_sso": False,
        "ok": ok,
        "reason": (
            "Studio SSO token expiry ok (fresh accepted, expired rejected); "
            "live hosted IdP Studio SSO still open"
            if ok else
            "Studio SSO token expiry incomplete; hosted IdP still open"
        ),
    }
    if not _write(evidence, ops_dir):
        return _linked_expiry()
    return evidence


def _write(evidence: dict, ops_dir: Path | None) -> bool:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "studio_sso_token_expiry_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return False
    dest.mkdir(parents=True, exist_ok=True)
    text = json.dumps(evidence, indent=2)
    if not write_text_unless_linked(dest, name, text):
        return False
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return True
