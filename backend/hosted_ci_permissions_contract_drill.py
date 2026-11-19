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


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _audit(path: Path) -> dict:
    from .finalization import folder_is_linked
    linked = folder_is_linked(path)
    text = "" if linked or not path.is_file() else path.read_text(encoding="utf-8")
    forbidden_hits = [item for item in FORBIDDEN if item in text]
    checks = {
        "present": (not linked) and path.is_file(),
        "permissions_block": "permissions:" in text,
        "contents_read": "contents: read" in text,
        "no_forbidden_write_scopes": not forbidden_hits,
    }
    return {
        "path": _label(path),
        "checks": checks,
        "forbidden_hits": forbidden_hits,
        "ok": all(checks.values()),
        "live_hosted_runners": False,
    }


def _linked_permissions() -> dict:
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "ok": False,
        "live_hosted_runners": False,
        "drill": "hosted_ci_permissions_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_ci_permissions_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_permissions()
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
    text = json.dumps(evidence, indent=2)
    name = "hosted_ci_permissions_contract_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_permissions()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_permissions()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
