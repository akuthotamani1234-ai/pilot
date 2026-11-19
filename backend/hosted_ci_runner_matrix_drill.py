"""Gates D/F: hosted CI runner matrix honesty snapshot (not executed).

Documents the broad multi-device and multi-browser runner shapes still required
before D/F can leave Partial. Does **not** boot those runners.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_ci_runner_matrix_drill.json"


def run_hosted_ci_runner_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    from .device_artifact_manifest_drill import run_device_artifact_manifest_drill
    from .hosted_runner_contract_drill import run_hosted_runner_contract_drill
    from .portfolio_artifact_manifest_drill import run_portfolio_artifact_manifest_drill

    contracts = run_hosted_runner_contract_drill(ops_dir=ops_dir)
    devices = run_device_artifact_manifest_drill(ops_dir=ops_dir)
    portfolios = run_portfolio_artifact_manifest_drill(ops_dir=ops_dir)
    matrix = {
        "multi_device": {
            "os": ["ubuntu-latest"],
            "kvm_required": True,
            "api_levels": [24, 30, 34],
            "appium": ">=3.0",
            "driver": "uiautomator2",
            "workflow": ".github/workflows/android-appium.yml",
            "workflow_exists": (
                ROOT / ".github/workflows/android-appium.yml"
            ).is_file(),
            "artifact_manifest_ok": bool(devices.get("ok")),
            "note": "Broad hosted multi-device product-matrix CI still open",
        },
        "multi_browser": {
            "os": ["ubuntu-latest"],
            "browsers": ["chromium", "firefox", "webkit"],
            "workflow": ".github/workflows/multi-browser-portfolios.yml",
            "workflow_exists": (
                ROOT / ".github/workflows/multi-browser-portfolios.yml"
            ).is_file(),
            "artifact_manifest_ok": bool(portfolios.get("ok")),
            "note": "Broad hosted multi-browser portfolio CI still open",
        },
    }
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_ci_runner_matrix",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_matrix_only",
        "matrix": matrix,
        "contracts_ok": bool(contracts.get("ok")),
        "ok": (
            bool(contracts.get("ok"))
            and bool(devices.get("ok"))
            and bool(portfolios.get("ok"))
            and matrix["multi_device"]["workflow_exists"]
            and matrix["multi_browser"]["workflow_exists"]
        ),
        "reason": (
            "Hosted CI runner matrix snapshot recorded; broad multi-device and "
            "multi-browser hosted runner execution still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_ci_runner_matrix_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_ci_runner_matrix_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
