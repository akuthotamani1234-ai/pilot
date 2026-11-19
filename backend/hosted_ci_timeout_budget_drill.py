"""Gates D/F: hosted CI job timeout budget contract (not dispatched).

Audits android-appium + multi-browser workflow ``timeout-minutes`` budgets.
Does **not** dispatch hosted runners — gates stay Incomplete.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_ci_timeout_budget_drill.json"

ANDROID_WF = ROOT / ".github" / "workflows" / "android-appium.yml"
BROWSER_WF = ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml"
TIMEOUT_RE = re.compile(r"timeout-minutes:\s*(\d+)")


def _budget(path: Path, *, minimum: int, maximum: int) -> dict:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    match = TIMEOUT_RE.search(text)
    minutes = int(match.group(1)) if match else None
    ok = (
        path.is_file()
        and minutes is not None
        and minimum <= minutes <= maximum
    )
    return {
        "path": str(path.relative_to(ROOT)) if path.is_file() else str(path),
        "timeout_minutes": minutes,
        "minimum": minimum,
        "maximum": maximum,
        "ok": ok,
        "live_hosted_runners": False,
    }


def run_hosted_ci_timeout_budget_drill(*, ops_dir: Path | None = None) -> dict:
    android = _budget(ANDROID_WF, minimum=30, maximum=120)
    browsers = _budget(BROWSER_WF, minimum=15, maximum=90)
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_ci_timeout_budget",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "android": android,
        "browsers": browsers,
        "live_hosted_runners": False,
        "ok": bool(android.get("ok")) and bool(browsers.get("ok")),
        "reason": (
            "Hosted CI timeout budget contract ok; "
            "broad hosted multi-device/browser runners still open"
            if android.get("ok") and browsers.get("ok") else
            "Hosted CI timeout budget incomplete; hosted runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_ci_timeout_budget_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_ci_timeout_budget_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
