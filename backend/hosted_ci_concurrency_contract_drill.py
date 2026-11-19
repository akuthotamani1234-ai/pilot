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


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _audit(path: Path) -> dict:
    from .finalization import folder_is_linked
    linked = folder_is_linked(path)
    text = "" if linked or not path.is_file() else path.read_text(encoding="utf-8")
    checks = {
        "present": (not linked) and path.is_file(),
        "workflow_dispatch": "workflow_dispatch:" in text,
        "manual_only": "pull_request:" not in text and "push:" not in text,
        "single_job": text.count("runs-on:") == 1,
    }
    return {
        "path": _label(path),
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


def _linked_concurrency() -> dict:
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "ok": False,
        "live_hosted_runners": False,
        "drill": "hosted_ci_concurrency_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_ci_concurrency_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    name = "hosted_ci_concurrency_contract_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_concurrency()
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
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_concurrency()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_concurrency()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
