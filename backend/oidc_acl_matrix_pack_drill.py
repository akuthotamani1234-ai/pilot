"""Gate I: OIDC ACL matrix pack (tid + email-domain + org/hd + groups).

Runs the loopback ACL drills as one matrix. Does **not** perform live hosted
IdP Studio SSO — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "oidc_acl_matrix_pack_drill.json"


def _linked_matrix() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "oidc_acl_matrix_pack",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_oidc_acl_matrix_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    from .oidc_email_domain_tenant_acl_drill import (
        run_oidc_email_domain_tenant_acl_drill,
    )
    from .oidc_groups_role_acl_drill import run_oidc_groups_role_acl_drill
    from .oidc_org_tenant_acl_drill import run_oidc_org_tenant_acl_drill
    from .oidc_tid_tenant_acl_drill import run_oidc_tid_tenant_acl_drill

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "oidc_acl_matrix_pack_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_matrix()

    started = time.perf_counter()
    parts = {}
    for key, fn in (
        ("tid", run_oidc_tid_tenant_acl_drill),
        ("email_domain", run_oidc_email_domain_tenant_acl_drill),
        ("org_hd", run_oidc_org_tenant_acl_drill),
        ("groups", run_oidc_groups_role_acl_drill),
    ):
        try:
            parts[key] = fn(ops_dir=ops_dir)
        except Exception as exc:
            parts[key] = {"ok": False, "reason": str(exc)[:160]}
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ok = all(bool((parts.get(k) or {}).get("ok")) for k in parts)
    evidence = {
        "gate_i_complete": False,
        "drill": "oidc_acl_matrix_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_ops_pack",
        "parts": {k: bool((v or {}).get("ok")) for k, v in parts.items()},
        "live_hosted_sso": False,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "reason": (
            f"OIDC ACL matrix pack ok in {elapsed_ms}ms "
            f"({sum(1 for v in parts.values() if v.get('ok'))}/{len(parts)}); "
            "live hosted IdP Studio SSO still open"
            if ok else
            "OIDC ACL matrix pack incomplete; hosted IdP still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_matrix()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_matrix()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
