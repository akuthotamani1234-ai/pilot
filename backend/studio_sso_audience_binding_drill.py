"""Gate I: Studio SSO audience binding (wrong aud rejected, loopback).

Proves loopback JWT validation rejects a mismatched ``aud`` while accepting
the configured audience. Hosted IdP Studio SSO still open —
``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_audience_binding_drill.json"


def run_studio_sso_audience_binding_drill(*, ops_dir: Path | None = None) -> dict:
    try:
        import jwt  # noqa: F401
    except ImportError:
        evidence = {
            "gate_i_complete": False,
            "drill": "studio_sso_audience_binding",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "PyJWT not installed — cannot run SSO audience binding drill",
        }
        _write(evidence, ops_dir)
        return evidence

    from .loopback_sso_drill import loopback_oidc_session
    from .oidc_jwt import validate_bearer

    expected_aud = "qpilot-loopback"
    wrong_aud = "qpilot-wrong-audience"
    prev_mode = os.environ.get("QPILOT_DASHBOARD_AUTH")
    os.environ["QPILOT_DASHBOARD_AUTH"] = "oidc"
    try:
        with loopback_oidc_session(audience=expected_aud) as good:
            good_result = dict(good["validate"] or {})

        with loopback_oidc_session(audience=wrong_aud) as bad:
            # Keep JWKS live; force expected audience so wrong aud must fail.
            os.environ["QPILOT_OIDC_AUDIENCE"] = expected_aud
            os.environ["QPILOT_OIDC_ISSUER"] = bad["issuer"]
            bad_result = validate_bearer(bad["token"], verify_signature=True)
    finally:
        if prev_mode is None:
            os.environ.pop("QPILOT_DASHBOARD_AUTH", None)
        else:
            os.environ["QPILOT_DASHBOARD_AUTH"] = prev_mode

    good_ok = bool(good_result.get("ok")) and bool(good_result.get("signature_verified"))
    bad_rejected = not bool(bad_result.get("ok"))
    ok = good_ok and bad_rejected
    evidence = {
        "gate_i_complete": False,
        "drill": "studio_sso_audience_binding",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "loopback_audience_binding",
        "expected_audience": expected_aud,
        "wrong_audience": wrong_aud,
        "good_ok": good_ok,
        "bad_rejected": bad_rejected,
        "bad_reason": (bad_result.get("reason") or "")[:160],
        "live_hosted_sso": False,
        "ok": ok,
        "reason": (
            "Studio SSO audience binding ok (good aud accepted, wrong aud rejected); "
            "live hosted IdP Studio SSO still open"
            if ok else
            "Studio SSO audience binding incomplete; hosted IdP still open"
        ),
    }
    _write(evidence, ops_dir)
    return evidence


def _write(evidence: dict, ops_dir: Path | None) -> None:
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "studio_sso_audience_binding_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "studio_sso_audience_binding_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
