"""Gates D/F: audit hosted workflow YAML for runner/artifact readiness.

Parses android-appium + multi-browser portfolio workflow files for
workflow_dispatch, runs-on, upload-artifact, and expected inputs.
Does **not** dispatch hosted runners — gates stay Incomplete.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_workflow_runner_audit_drill.json"

ANDROID_WF = ROOT / ".github" / "workflows" / "android-appium.yml"
BROWSER_WF = ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml"


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _audit(path: Path, *, required_inputs: tuple[str, ...] = ()) -> dict:
    from .finalization import folder_is_linked
    linked = folder_is_linked(path)
    text = "" if linked or not path.is_file() else path.read_text(encoding="utf-8")
    checks = {
        "present": (not linked) and path.is_file(),
        "workflow_dispatch": "workflow_dispatch:" in text,
        "runs_on": "runs-on:" in text,
        "upload_artifact": "upload-artifact@" in text,
        "contents_read": "contents: read" in text,
        "gate_complete_false_guard": "gate_" in text or "still open" in text.lower()
        or "Incomplete" in text or "KVM" in text or "Hosted" in text,
    }
    input_hits = {name: (f"{name}:" in text) for name in required_inputs}
    ok = (
        checks["present"]
        and checks["workflow_dispatch"]
        and checks["runs_on"]
        and checks["upload_artifact"]
        and all(input_hits.values())
    )
    return {
        "path": _label(path),
        "checks": checks,
        "required_inputs": input_hits,
        "ok": ok,
        "live_hosted_runners": False,
    }


def _linked_runner_audit() -> dict:
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "ok": False,
        "live_hosted_runners": False,
        "drill": "hosted_workflow_runner_audit",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_workflow_runner_audit_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    name = "hosted_workflow_runner_audit_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_runner_audit()
    android = _audit(
        ANDROID_WF,
        required_inputs=("api_level", "include_api24_smoke", "artifact_prefix"),
    )
    browsers = _audit(
        BROWSER_WF,
        required_inputs=("engines", "portfolio", "artifact_prefix"),
    )
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_workflow_runner_audit",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "workflow_yaml_audit",
        "android": android,
        "browsers": browsers,
        "live_hosted_runners": False,
        "ok": bool(android.get("ok")) and bool(browsers.get("ok")),
        "reason": (
            "Hosted workflow runner audit ok; "
            "broad hosted multi-device/browser runners still open"
            if android.get("ok") and browsers.get("ok") else
            "Hosted workflow runner audit incomplete; hosted runners still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_runner_audit()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_runner_audit()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
