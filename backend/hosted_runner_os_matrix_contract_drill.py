"""Gates D/F: hosted runner OS/label matrix contract (not dispatched).

Records expected runner OS labels for android-appium + multi-browser jobs.
Does **not** dispatch hosted runners — gates stay Incomplete.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_runner_os_matrix_contract_drill.json"

ANDROID_WF = ROOT / ".github" / "workflows" / "android-appium.yml"
BROWSER_WF = ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml"
RUNS_ON_RE = re.compile(r"runs-on:\s*([^\n#]+)")


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _audit(path: Path, *, expected_substring: str) -> dict:
    from .finalization import folder_is_linked
    linked = folder_is_linked(path)
    text = "" if linked or not path.is_file() else path.read_text(encoding="utf-8")
    matches = [m.group(1).strip().strip('"').strip("'") for m in RUNS_ON_RE.finditer(text)]
    ok = (not linked) and path.is_file() and any(expected_substring in m for m in matches)
    return {
        "path": _label(path),
        "runs_on": matches,
        "expected_substring": expected_substring,
        "ok": ok,
        "live_hosted_runners": False,
    }


def _linked_runner_os() -> dict:
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "ok": False,
        "live_hosted_runners": False,
        "drill": "hosted_runner_os_matrix_contract",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_runner_os_matrix_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    name = "hosted_runner_os_matrix_contract_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_runner_os()
    android = _audit(ANDROID_WF, expected_substring="ubuntu")
    browsers = _audit(BROWSER_WF, expected_substring="ubuntu")
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_runner_os_matrix_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "desired_matrix": {
            "android": ["ubuntu-latest (KVM-capable preferred)"],
            "browsers": ["ubuntu-latest"],
            "note": "Broad multi-device/browser hosted runners still open",
        },
        "android": android,
        "browsers": browsers,
        "live_hosted_runners": False,
        "ok": bool(android.get("ok")) and bool(browsers.get("ok")),
        "reason": (
            "Hosted runner OS matrix contract recorded (ubuntu workflows); "
            "broad hosted multi-device/browser runners still open"
            if android.get("ok") and browsers.get("ok") else
            "Hosted runner OS matrix incomplete; hosted runners still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_runner_os()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_runner_os()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
