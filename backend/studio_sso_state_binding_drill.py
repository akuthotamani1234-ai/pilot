"""Gate I: Studio SSO state binding (mismatch rejected).

Proves ``validate_sso_state`` accepts the expected state and rejects a wrong
one. Hosted IdP Studio SSO still open — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "studio_sso_state_binding_drill.json"


def run_studio_sso_state_binding_drill(*, ops_dir: Path | None = None) -> dict:
    from .studio_oidc_callback import validate_sso_state

    expected = "studio-sso-state-1"
    good = validate_sso_state(expected, expected=expected)
    bad = validate_sso_state("wrong-state", expected=expected)
    unset = validate_sso_state("anything", expected="")
    ok = (
        bool(good.get("ok"))
        and bool(good.get("state_ok"))
        and not bool(bad.get("ok"))
        and bool(unset.get("ok"))
        and unset.get("state_enforced") is False
    )
    evidence = {
        "gate_i_complete": False,
        "drill": "studio_sso_state_binding",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "state_binding_local",
        "expected_state": expected,
        "good_ok": bool(good.get("ok")),
        "bad_rejected": not bool(bad.get("ok")),
        "unset_passthrough": bool(unset.get("ok")) and unset.get("state_enforced") is False,
        "bad_reason": (bad.get("reason") or "")[:160],
        "live_hosted_sso": False,
        "ok": ok,
        "reason": (
            "Studio SSO state binding ok (match accepted, mismatch rejected); "
            "live hosted IdP Studio SSO still open"
            if ok else
            "Studio SSO state binding incomplete; hosted IdP still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "studio_sso_state_binding_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "studio_sso_state_binding_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
