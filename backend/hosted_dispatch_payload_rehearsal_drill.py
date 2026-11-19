"""Gates D/F: rehearse workflow_dispatch payload shapes (no hosted run).

Builds dry-run JSON payloads matching Android Appium + multi-browser
workflow inputs. Does **not** call GitHub Actions —
``gate_d_complete`` / ``gate_f_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_dispatch_payload_rehearsal_drill.json"

ANDROID_WF = ROOT / ".github" / "workflows" / "android-appium.yml"
BROWSER_WF = ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml"


def _payload(workflow: str, inputs: dict) -> dict:
    return {
        "ref": "cursor/qpilot-x-phase0-baseline-f72b",
        "workflow": workflow,
        "inputs": inputs,
        "dispatched": False,
    }


def run_hosted_dispatch_payload_rehearsal_drill(*, ops_dir: Path | None = None) -> dict:
    android_exists = ANDROID_WF.is_file()
    browser_exists = BROWSER_WF.is_file()
    android_payload = _payload(
        "android-appium.yml",
        {
            "api_level": "30",
            "include_api24_smoke": "true",
            "artifact_prefix": "qpilot-android-matrix",
        },
    )
    browser_payload = _payload(
        "multi-browser-portfolios.yml",
        {
            "engines": "chromium,firefox,webkit",
            "portfolio": "demo_store",
            "artifact_prefix": "qpilot-browser-portfolio",
        },
    )
    # Shape checks only — never invoke gh workflow run.
    android_ok = (
        android_exists
        and isinstance(android_payload["inputs"].get("api_level"), str)
        and android_payload["dispatched"] is False
    )
    browser_ok = (
        browser_exists
        and "chromium" in str(browser_payload["inputs"].get("engines") or "")
        and browser_payload["dispatched"] is False
    )
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_dispatch_payload_rehearsal",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "dry_run_payload_only",
        "android": {
            "workflow_present": android_exists,
            "payload": android_payload,
            "ok": android_ok,
        },
        "browsers": {
            "workflow_present": browser_exists,
            "payload": browser_payload,
            "ok": browser_ok,
        },
        "ok": android_ok and browser_ok,
        "reason": (
            "Hosted dispatch payloads rehearsed (not dispatched); "
            "broad hosted CI runner execution still open"
            if android_ok and browser_ok
            else "Hosted dispatch payload rehearsal incomplete; hosted runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_dispatch_payload_rehearsal_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_dispatch_payload_rehearsal_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
