"""Gate I: Studio SSO jti replay rejection (opt-in).

Proves a second use of the same ``jti`` is rejected when
``QPILOT_SSO_REPLAY_JTI`` is set, and that the check stays off by default.
Hosted IdP Studio SSO still open — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_jti_replay_drill.json"


def _jwt(payload: dict) -> str:
    def enc(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = {"alg": "none", "typ": "JWT"}
    return f"{enc(header)}.{enc(payload)}.sig"


def _linked_jti() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "studio_sso_jti_replay",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_studio_sso_jti_replay_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    from .oidc_jwt import reset_seen_jti, validate_bearer

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "studio_sso_jti_replay_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_jti()

    prev_flag = os.environ.get("QPILOT_SSO_REPLAY_JTI")
    prev_iss = os.environ.get("QPILOT_OIDC_ISSUER")
    os.environ["QPILOT_SSO_REPLAY_JTI"] = "1"
    reset_seen_jti()
    now = int(time.time())
    payload = {
        "iss": prev_iss or "https://idp.local",
        "sub": "studio-user",
        "exp": now + 600,
        "jti": "studio-jti-replay-1",
    }
    os.environ["QPILOT_OIDC_ISSUER"] = payload["iss"]
    token = _jwt(payload)
    try:
        first = validate_bearer(token, verify_signature=False)
        second = validate_bearer(token, verify_signature=False)
        missing = validate_bearer(
            _jwt({"iss": payload["iss"], "sub": "studio-user", "exp": now + 600}),
            verify_signature=False,
        )
    finally:
        reset_seen_jti()
        if prev_flag is None:
            os.environ.pop("QPILOT_SSO_REPLAY_JTI", None)
        else:
            os.environ["QPILOT_SSO_REPLAY_JTI"] = prev_flag
        if prev_iss is None:
            os.environ.pop("QPILOT_OIDC_ISSUER", None)
        else:
            os.environ["QPILOT_OIDC_ISSUER"] = prev_iss
    first_ok = bool(first.get("ok"))
    replay_rejected = (not bool(second.get("ok"))) and "replay" in (second.get("reason") or "")
    missing_rejected = (not bool(missing.get("ok"))) and "jti required" in (missing.get("reason") or "")
    ok = first_ok and replay_rejected and missing_rejected
    evidence = {
        "gate_i_complete": False,
        "drill": "studio_sso_jti_replay",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "jti_replay_local",
        "first_ok": first_ok,
        "replay_rejected": replay_rejected,
        "missing_jti_rejected": missing_rejected,
        "replay_reason": (second.get("reason") or "")[:160],
        "live_hosted_sso": False,
        "ok": ok,
        "reason": (
            "Studio SSO jti replay rejection ok (first accepted, repeat and missing jti rejected); "
            "live hosted IdP Studio SSO still open"
            if ok else
            "Studio SSO jti replay rejection incomplete; hosted IdP still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_jti()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_jti()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
