"""Gate I: hosted IdP SSO readiness pack (contract + readiness + ACL drills).

Bundles IdP contract/readiness with principal bootstrap + email-domain ACL.
Does **not** perform live hosted IdP Studio SSO — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_idp_sso_readiness_pack_drill.json"


def run_hosted_idp_sso_readiness_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .hosted_idp_contract_drill import run_hosted_idp_contract_drill
    from .hosted_idp_readiness_drill import run_hosted_idp_readiness_drill
    from .oidc_email_domain_tenant_acl_drill import (
        run_oidc_email_domain_tenant_acl_drill,
    )
    from .studio_sso_principal_bootstrap_drill import (
        run_studio_sso_principal_bootstrap_drill,
    )

    started = time.perf_counter()
    parts = {}
    for key, fn in (
        ("contract", run_hosted_idp_contract_drill),
        ("readiness", run_hosted_idp_readiness_drill),
        ("principal_bootstrap", run_studio_sso_principal_bootstrap_drill),
        ("email_domain_acl", run_oidc_email_domain_tenant_acl_drill),
    ):
        try:
            parts[key] = fn(ops_dir=ops_dir)
        except Exception as exc:
            parts[key] = {"ok": False, "reason": str(exc)[:160]}
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ok = all(bool((parts.get(k) or {}).get("ok")) for k in parts)
    evidence = {
        "gate_i_complete": False,
        "drill": "hosted_idp_sso_readiness_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_ops_pack",
        "parts": {k: bool((v or {}).get("ok")) for k, v in parts.items()},
        "live_hosted_sso": False,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "reason": (
            f"Hosted IdP SSO readiness pack ok in {elapsed_ms}ms; "
            "live hosted IdP Studio SSO still open"
            if ok else
            "Hosted IdP SSO readiness pack incomplete; hosted IdP still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_idp_sso_readiness_pack_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_idp_sso_readiness_pack_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
