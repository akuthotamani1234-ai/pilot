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


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _budget(path: Path, *, minimum: int, maximum: int) -> dict:
    from .finalization import folder_is_linked
    linked = folder_is_linked(path)
    text = "" if linked or not path.is_file() else path.read_text(encoding="utf-8")
    match = TIMEOUT_RE.search(text)
    minutes = int(match.group(1)) if match else None
    ok = (
        (not linked)
        and path.is_file()
        and minutes is not None
        and minimum <= minutes <= maximum
    )
    return {
        "path": _label(path),
        "timeout_minutes": minutes,
        "minimum": minimum,
        "maximum": maximum,
        "ok": ok,
        "live_hosted_runners": False,
    }


def _linked_timeout() -> dict:
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "ok": False,
        "live_hosted_runners": False,
        "drill": "hosted_ci_timeout_budget",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_ci_timeout_budget_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_timeout()
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
    text = json.dumps(evidence, indent=2)
    name = "hosted_ci_timeout_budget_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_timeout()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_timeout()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
