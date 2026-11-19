"""Gates D/F: hosted CI artifact retention contract (not uploaded to hosted CI).

Records retention policy and required artifact names for android-appium and
multi-browser portfolio workflows. Does **not** run hosted runners —
gates stay Incomplete.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_ci_artifact_retention_contract_drill.json"

ANDROID_ARTIFACTS = (
    "android_appium_ci_contract.json",
    "android_appium_product_matrix_drill.json",
    "android_emulator_smoke_drill.json",
    "multi_api_android_matrix_drill.json",
    "device_matrix_drill.json",
    "device_artifact_manifest_drill.json",
    "multi_device_ci_contract.json",
    "android_device_ci_readiness_pack_drill.json",
    "hosted_workflow_runner_audit_drill.json",
)
BROWSER_ARTIFACTS = (
    "multi_browser_portfolio_suite_drill.json",
    "portfolio_artifact_manifest_drill.json",
    "multi_browser_ci_contract.json",
    "browser_portfolio_ci_readiness_pack_drill.json",
    "hosted_workflow_runner_audit_drill.json",
)


def run_hosted_ci_artifact_retention_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    android_present = [n for n in ANDROID_ARTIFACTS if (ops / n).is_file()]
    browser_present = [n for n in BROWSER_ARTIFACTS if (ops / n).is_file()]
    contract = {
        "retention_days": 14,
        "compression": "zip",
        "android_workflow": ".github/workflows/android-appium.yml",
        "browser_workflow": ".github/workflows/multi-browser-portfolios.yml",
        "android_artifact_name": "android-appium-matrix-evidence",
        "browser_artifact_name": "multi-browser-portfolio-evidence",
        "note": "Contract only; hosted multi-device/browser runners still open",
    }
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_ci_artifact_retention_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "contract": contract,
        "android": {
            "required": list(ANDROID_ARTIFACTS),
            "present": android_present,
            "missing": [n for n in ANDROID_ARTIFACTS if n not in android_present],
        },
        "browsers": {
            "required": list(BROWSER_ARTIFACTS),
            "present": browser_present,
            "missing": [n for n in BROWSER_ARTIFACTS if n not in browser_present],
        },
        "live_hosted_runners": False,
        "ok": (
            len(android_present) == len(ANDROID_ARTIFACTS)
            and len(browser_present) == len(BROWSER_ARTIFACTS)
        ),
        "reason": (
            f"Hosted CI artifact retention contract recorded "
            f"(android {len(android_present)}/{len(ANDROID_ARTIFACTS)}, "
            f"browser {len(browser_present)}/{len(BROWSER_ARTIFACTS)}); "
            "broad hosted multi-device/browser runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_ci_artifact_retention_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = (
            ROOT / "artifacts" / "ops" / "hosted_ci_artifact_retention_contract_drill.json"
        )
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
