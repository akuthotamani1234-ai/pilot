"""Gate I: dashboard auth mode matrix drill (none/bearer/webhook/principal/oidc).

Offline contract only — live hosted IdP SSO still open. gate_i_complete stays False.
"""
from __future__ import annotations

import base64
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "dashboard_auth_matrix_drill.json"

_AUTH_ENV = (
    "QPILOT_DASHBOARD_AUTH",
    "BLOWAI_DASHBOARD_AUTH",
    "QPILOT_DASHBOARD_TOKEN",
    "BLOWAI_DASHBOARD_TOKEN",
    "WEBHOOK_TOKEN",
    "QPILOT_OIDC_ISSUER",
    "QPILOT_OIDC_AUDIENCE",
)


@contextmanager
def _env(overrides: dict[str, str | None]):
    saved = {k: os.environ.get(k) for k in _AUTH_ENV}
    try:
        for key in _AUTH_ENV:
            if key in overrides:
                val = overrides[key]
                if val is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = val
            else:
                os.environ.pop(key, None)
        yield
    finally:
        for key, val in saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def _b64(obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def run_dashboard_auth_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    from backend import tenancy_store as ts
    from backend.dashboard_auth import authorize
    from backend.tenancy_store import upsert_principal, upsert_tenant

    rows: list[dict] = []
    work = Path(ops_dir) / "dashboard_auth_work" if ops_dir else (
        ROOT / "artifacts" / "ops" / "dashboard_auth_work"
    )
    work.mkdir(parents=True, exist_ok=True)
    db = work / "auth.sqlite"

    # none
    with _env({}):
        out = authorize(None)
        rows.append({"mode": "none", "case": "open", "ok": bool(out.get("ok")),
                     "expected_ok": True, "pass": bool(out.get("ok"))})

    # bearer
    with _env({"QPILOT_DASHBOARD_AUTH": "bearer", "QPILOT_DASHBOARD_TOKEN": "matrix-secret"}):
        bad = authorize("Bearer wrong")
        good = authorize("Bearer matrix-secret")
        rows.append({"mode": "bearer", "case": "reject_bad", "ok": bool(bad.get("ok")),
                     "expected_ok": False, "pass": not bad.get("ok")})
        rows.append({"mode": "bearer", "case": "accept_good", "ok": bool(good.get("ok")),
                     "expected_ok": True, "pass": bool(good.get("ok"))})

    # webhook
    hook = "hook-secret"
    bad_hook = "nope"
    with _env({"QPILOT_DASHBOARD_AUTH": "webhook", "WEBHOOK_TOKEN": hook}):
        via_header = authorize(None, x_qa_token=hook)
        via_bearer = authorize(f"Bearer {hook}")
        reject = authorize(None, x_qa_token=bad_hook)
        rows.append({"mode": "webhook", "case": "x_qa_token", "ok": bool(via_header.get("ok")),
                     "expected_ok": True, "pass": bool(via_header.get("ok"))})
        rows.append({"mode": "webhook", "case": "bearer", "ok": bool(via_bearer.get("ok")),
                     "expected_ok": True, "pass": bool(via_bearer.get("ok"))})
        rows.append({"mode": "webhook", "case": "reject", "ok": bool(reject.get("ok")),
                     "expected_ok": False, "pass": not reject.get("ok")})

    # principal
    prev_db = ts.DEFAULT_DB
    try:
        ts.DEFAULT_DB = db
        upsert_tenant("t1", "Tenant", db_path=db)
        upsert_principal("p-op", "t1", "op@ex.test", "operator", db_path=db)
        upsert_principal("p-view", "t1", "v@ex.test", "viewer", db_path=db)
        with _env({"QPILOT_DASHBOARD_AUTH": "principal"}):
            op_ok = authorize("Bearer p-op")
            view_deny = authorize("Bearer p-view")
            missing = authorize("Bearer missing")
            rows.append({"mode": "principal", "case": "operator", "ok": bool(op_ok.get("ok")),
                         "expected_ok": True, "pass": bool(op_ok.get("ok"))})
            rows.append({"mode": "principal", "case": "viewer_deny", "ok": bool(view_deny.get("ok")),
                         "expected_ok": False, "pass": not view_deny.get("ok")})
            rows.append({"mode": "principal", "case": "unknown", "ok": bool(missing.get("ok")),
                         "expected_ok": False, "pass": not missing.get("ok")})
    finally:
        ts.DEFAULT_DB = prev_db

    # oidc (claim check plus principal RBAC; live IdP SSO still open)
    prev_db = ts.DEFAULT_DB
    ts.DEFAULT_DB = db
    try:
        upsert_tenant("t1", "Tenant", db_path=db)
        upsert_principal("user-1", "t1", "user@ex.test", "operator", db_path=db)
        with _env({
            "QPILOT_DASHBOARD_AUTH": "oidc",
            "QPILOT_OIDC_ISSUER": "https://idp.example",
            "QPILOT_OIDC_AUDIENCE": "qpilot-dashboard",
        }):
            payload = {
                "iss": "https://idp.example",
                "aud": "qpilot-dashboard",
                "sub": "user-1",
                "exp": int(time.time()) + 3600,
            }
            token = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}.sig"
            oidc_ok = authorize(f"Bearer {token}")
            oidc_bad = authorize("Bearer not-a-jwt")
    finally:
        ts.DEFAULT_DB = prev_db
        rows.append({
            "mode": "oidc", "case": "valid_claims", "ok": bool(oidc_ok.get("ok")),
            "expected_ok": True,
            "pass": bool(oidc_ok.get("ok")) and oidc_ok.get("gate_i_complete") is False,
        })
        rows.append({
            "mode": "oidc", "case": "reject_garbage", "ok": bool(oidc_bad.get("ok")),
            "expected_ok": False, "pass": not oidc_bad.get("ok"),
        })

    modes_covered = sorted({r["mode"] for r in rows})
    evidence = {
        "gate_i_complete": False,
        "drill": "dashboard_auth_mode_matrix",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "modes_covered": modes_covered,
        "cases": rows,
        "passed": sum(1 for r in rows if r["pass"]),
        "failed": sum(1 for r in rows if not r["pass"]),
        "ok": all(r["pass"] for r in rows) and modes_covered == [
            "bearer", "none", "oidc", "principal", "webhook",
        ],
        "reason": (
            "Dashboard auth modes none/bearer/webhook/principal/oidc exercised offline; "
            "live hosted IdP SSO still open"
        ),
    }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "dashboard_auth_matrix_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "dashboard_auth_matrix_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
