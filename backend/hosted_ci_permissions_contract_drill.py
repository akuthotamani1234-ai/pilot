"""Gates D/F: hosted CI workflow permissions contract (not dispatched).

Audits android-appium + multi-browser workflows for least-privilege
``permissions: contents: read`` and absence of write scopes. Does **not**
dispatch hosted runners — gates stay Incomplete.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_ci_permissions_contract_drill.json"

ANDROID_WF = ROOT / ".github" / "workflows" / "android-appium.yml"
BROWSER_WF = ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml"
FORBIDDEN = (
    "contents: write",
    "pull-requests: write",
    "actions: write",
    "packages: write",
    "id-token: write",
)


def _audit(path: Path) -> dict:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    forbidden_hits = [item for item in FORBIDDEN if item in text]
    checks = {
        "present": path.is_file(),
        "permissions_block": "permissions:" in text,
        "contents_read": "contents: read" in text,
        "no_forbidden_write_scopes": not forbidden_hits,
    }
    return {
        "path": str(path.relative_to(ROOT)) if path.is_file() else str(path),
        "checks": checks,
        "forbidden_hits": forbidden_hits,
        "ok": all(checks.values()),
        "live_hosted_runners": False,
    }


def run_hosted_ci_permissions_contract_drill(*, ops_dir: Path | None = None) -> dict:
    android = _audit(ANDROID_WF)
    browsers = _audit(BROWSER_WF)
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_ci_permissions_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "android": android,
        "browsers": browsers,
        "live_hosted_runners": False,
        "ok": bool(android.get("ok")) and bool(browsers.get("ok")),
        "reason": (
            "Hosted CI permissions contract ok (contents: read); "
            "broad hosted multi-device/browser runners still open"
            if android.get("ok") and browsers.get("ok") else
            "Hosted CI permissions contract incomplete; hosted runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_ci_permissions_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_ci_permissions_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
