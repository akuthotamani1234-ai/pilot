"""Gates D/F: hosted CI concurrency / cancel-in-progress contract (not run).

Audits android-appium + multi-browser workflows for optional concurrency
guards. Does **not** dispatch hosted runners — gates stay Incomplete.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_ci_concurrency_contract_drill.json"

ANDROID_WF = ROOT / ".github" / "workflows" / "android-appium.yml"
BROWSER_WF = ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml"


def _audit(path: Path) -> dict:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    checks = {
        "present": path.is_file(),
        "workflow_dispatch": "workflow_dispatch:" in text,
        "manual_only": "pull_request:" not in text and "push:" not in text,
        "single_job": text.count("runs-on:") == 1,
    }
    return {
        "path": str(path.relative_to(ROOT)) if path.is_file() else str(path),
        "checks": checks,
        "concurrency_group_declared": "concurrency:" in text,
        "cancel_in_progress_declared": "cancel-in-progress:" in text,
        "ok": all(checks.values()),
        "live_hosted_runners": False,
        "note": (
            "Manual workflow_dispatch jobs may omit concurrency groups; "
            "contract records presence/absence without requiring them yet"
        ),
    }


def run_hosted_ci_concurrency_contract_drill(*, ops_dir: Path | None = None) -> dict:
    android = _audit(ANDROID_WF)
    browsers = _audit(BROWSER_WF)
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_ci_concurrency_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "android": android,
        "browsers": browsers,
        "live_hosted_runners": False,
        "ok": bool(android.get("ok")) and bool(browsers.get("ok")),
        "reason": (
            "Hosted CI concurrency contract recorded (manual dispatch jobs); "
            "broad hosted multi-device/browser runners still open"
            if android.get("ok") and browsers.get("ok") else
            "Hosted CI concurrency contract incomplete; hosted runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_ci_concurrency_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_ci_concurrency_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
