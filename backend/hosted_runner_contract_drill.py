"""Gates D/F: offline hosted-runner matrix contracts (not executed).

Documents required multi-device Appium and multi-browser portfolio CI runner
shapes plus artifact paths. Does **not** run those runners —
``gate_d_complete`` / ``gate_f_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "docs" / "ops-evidence"


def _linked_runner() -> dict:
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "ok": False,
        "drill": "hosted_runner_contracts",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def _workflow_present(path: Path) -> bool:
    from .finalization import folder_is_linked

    return (not folder_is_linked(path)) and path.is_file()


def run_hosted_runner_contract_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE_DIR
    browser_name = "multi_browser_ci_contract.json"
    device_name = "multi_device_ci_contract.json"
    if (folder_is_linked(dest) or folder_is_linked(dest / browser_name)
            or folder_is_linked(dest / device_name)):
        return _linked_runner()

    ran_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    browser = {
        "gate_f_complete": False,
        "drill": "multi_browser_ci_contract",
        "ran_at": ran_at,
        "ok": True,
        "kind": "contract_only",
        "reason": (
            "Offline CI contract for multi-browser portfolio artifacts; "
            "broad hosted multi-browser runner matrix still open"
        ),
        "required_runner": {
            "os": "ubuntu-latest",
            "browsers": ["chromium", "firefox", "webkit"],
            "playwright_install": "--with-deps chromium firefox webkit",
            "python": "3.13",
        },
        "artifact_paths": [
            "docs/ops-evidence/multi_browser_portfolio_suite_drill.json",
            "docs/ops-evidence/compatibility_portfolio_drill.json",
            "docs/ops-evidence/a11y_portfolio_drill.json",
            "docs/ops-evidence/locale_portfolio_drill.json",
            "docs/ops-evidence/security_portfolio_drill.json",
            "docs/ops-evidence/perf_portfolio_drill.json",
            "docs/ops-evidence/visual_portfolio_drill.json",
        ],
        "drill_api": "POST /api/ops/drills/multi-browser-portfolio-suite",
        "workflow": ".github/workflows/multi-browser-portfolios.yml",
        "workflow_exists": _workflow_present(ROOT / ".github/workflows/multi-browser-portfolios.yml"),
        "note": (
            "Default PR CI remains Windows quick tests; workflow_dispatch multi-browser "
            "job uploads suite evidence; broad hosted matrix still open"
        ),
    }
    device = {
        "gate_d_complete": False,
        "drill": "multi_device_ci_contract",
        "ran_at": ran_at,
        "ok": True,
        "kind": "contract_only",
        "reason": (
            "Offline CI contract for multi-device Appium product-matrix artifacts; "
            "broad multi-device CI runners still open"
        ),
        "required_runner": {
            "os": "ubuntu-latest",
            "kvm": True,
            "api_levels": [24, 30, 34],
            "appium": ">=3.0",
            "driver": "uiautomator2",
            "env": ["ANDROID_HOME", "APPIUM_HOME", "BLOWAI_ANDROID_E2E=1"],
        },
        "artifact_paths": [
            "docs/ops-evidence/android_appium_product_matrix_drill.json",
            "docs/ops-evidence/android_emulator_smoke_drill.json",
            "docs/ops-evidence/multi_api_android_matrix_drill.json",
            "docs/ops-evidence/device_matrix_drill.json",
        ],
        "drill_api": "POST /api/ops/drills/multi-api-android-matrix",
        "workflow": ".github/workflows/android-appium.yml",
        "workflow_exists": _workflow_present(ROOT / ".github/workflows/android-appium.yml"),
        "related_contract": "docs/ops-evidence/android_appium_ci_contract.json",
        "note": (
            "API24 is adb smoke only; Appium needs API26+. Full AVD boot matrix on "
            "ubuntu+KVM still open"
        ),
    }
    browser_text = json.dumps(browser, indent=2)
    device_text = json.dumps(device, indent=2)
    if (folder_is_linked(dest) or folder_is_linked(dest / browser_name)
            or folder_is_linked(dest / device_name)):
        return _linked_runner()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, browser_name, browser_text):
        return _linked_runner()
    if not write_text_unless_linked(dest, device_name, device_text):
        return _linked_runner()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        for name, text in ((browser_name, browser_text), (device_name, device_text)):
            if not folder_is_linked(art) and not folder_is_linked(art / name):
                art.mkdir(parents=True, exist_ok=True)
                write_text_unless_linked(art, name, text)

    ok = bool(browser.get("ok") and device.get("ok")
              and browser.get("workflow_exists") and device.get("workflow_exists"))
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_runner_contracts",
        "ran_at": ran_at,
        "ok": ok,
        "multi_browser": browser,
        "multi_device": device,
        "reason": (
            "Hosted runner contracts recorded for multi-browser + multi-device; "
            "broad hosted CI runner execution still open"
        ),
    }
