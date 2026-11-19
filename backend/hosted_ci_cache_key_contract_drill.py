"""Gates D/F: hosted CI dependency cache-key contract (not dispatched).

Records expected cache keys for Appium / Playwright portfolio runners.
Does **not** boot hosted runners — gates stay Incomplete.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_ci_cache_key_contract_drill.json"

ANDROID_WF = ROOT / ".github" / "workflows" / "android-appium.yml"
BROWSER_WF = ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml"

LOCAL_PARTIAL = (
    "hosted_ci_runner_matrix_drill.json",
    "hosted_ci_timeout_budget_drill.json",
    "hosted_ci_concurrency_contract_drill.json",
    "hosted_runner_os_matrix_contract_drill.json",
    "workflow_dispatch_contract_drill.json",
)


def _wf_audit(path: Path) -> dict:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "path": str(path.relative_to(ROOT)) if path.is_file() else str(path),
        "present": path.is_file(),
        "actions_cache_mentioned": "actions/cache" in text or "cache:" in text,
        "workflow_dispatch": "workflow_dispatch:" in text,
    }


def run_hosted_ci_cache_key_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    contract = {
        "android": {
            "keys": [
                "qpilot-android-${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}",
                "qpilot-android-${{ runner.os }}-avd-api${{ matrix.api }}",
            ],
            "restore_keys": [
                "qpilot-android-${{ runner.os }}-pip-",
                "qpilot-android-${{ runner.os }}-avd-",
            ],
            "workflow": _wf_audit(ANDROID_WF),
        },
        "browsers": {
            "keys": [
                "qpilot-browsers-${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}",
                "qpilot-browsers-${{ runner.os }}-playwright-${{ hashFiles('**/package-lock.json') }}",
            ],
            "restore_keys": [
                "qpilot-browsers-${{ runner.os }}-pip-",
                "qpilot-browsers-${{ runner.os }}-playwright-",
            ],
            "workflow": _wf_audit(BROWSER_WF),
        },
        "note": "Cache-key contract only; live hosted multi-device/browser runners still required",
    }
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_ci_cache_key_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "contract": contract,
        "live_hosted_runners": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": (
            len(present) == len(LOCAL_PARTIAL)
            and bool(contract["android"]["workflow"]["present"])
            and bool(contract["browsers"]["workflow"]["present"])
        ),
        "reason": (
            f"Hosted CI cache-key contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "broad hosted multi-device/browser runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_ci_cache_key_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_ci_cache_key_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
