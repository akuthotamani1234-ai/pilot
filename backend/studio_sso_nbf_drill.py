"""Gate I: Studio SSO nbf (not-before) rejection.

Proves a JWT whose ``nbf`` is in the future is rejected, and a current token
is accepted. Hosted IdP Studio SSO still open — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_nbf_drill.json"


def _jwt(payload: dict) -> str:
    def enc(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = {"alg": "none", "typ": "JWT"}
    return f"{enc(header)}.{enc(payload)}.sig"


def run_studio_sso_nbf_drill(*, ops_dir: Path | None = None) -> dict:
    from .oidc_jwt import validate_bearer

    prev_iss = os.environ.get("QPILOT_OIDC_ISSUER")
    prev_aud = os.environ.get("QPILOT_OIDC_AUDIENCE")
    iss = prev_iss or "https://idp.local"
    os.environ["QPILOT_OIDC_ISSUER"] = iss
    os.environ.pop("QPILOT_OIDC_AUDIENCE", None)
    now = int(time.time())
    try:
        current = validate_bearer(
            _jwt({"iss": iss, "sub": "studio-user", "exp": now + 600, "nbf": now - 5}),
            verify_signature=False,
        )
        future = validate_bearer(
            _jwt({"iss": iss, "sub": "studio-user", "exp": now + 600, "nbf": now + 600}),
            verify_signature=False,
        )
        bad = validate_bearer(
            _jwt({"iss": iss, "sub": "studio-user", "exp": now + 600, "nbf": "soon"}),
            verify_signature=False,
        )
    finally:
        if prev_iss is None:
            os.environ.pop("QPILOT_OIDC_ISSUER", None)
        else:
            os.environ["QPILOT_OIDC_ISSUER"] = prev_iss
        if prev_aud is None:
            os.environ.pop("QPILOT_OIDC_AUDIENCE", None)
        else:
            os.environ["QPILOT_OIDC_AUDIENCE"] = prev_aud
    current_ok = bool(current.get("ok"))
    future_rejected = (not bool(future.get("ok"))) and "not yet valid" in (future.get("reason") or "")
    bad_rejected = (not bool(bad.get("ok"))) and "not a number" in (bad.get("reason") or "")
    ok = current_ok and future_rejected and bad_rejected
    evidence = {
        "gate_i_complete": False,
        "drill": "studio_sso_nbf",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "nbf_local",
        "current_ok": current_ok,
        "future_rejected": future_rejected,
        "bad_nbf_rejected": bad_rejected,
        "future_reason": (future.get("reason") or "")[:160],
        "live_hosted_sso": False,
        "ok": ok,
        "reason": (
            "Studio SSO nbf check ok (current accepted, future and non-numeric nbf rejected); "
            "live hosted IdP Studio SSO still open"
            if ok else
            "Studio SSO nbf check incomplete; hosted IdP still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "studio_sso_nbf_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "studio_sso_nbf_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
