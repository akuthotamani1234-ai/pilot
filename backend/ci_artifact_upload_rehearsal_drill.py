"""Gates D/F: local CI artifact upload rehearsal (not hosted runners).

Stages hashed Appium + multi-browser evidence into an upload-shaped bundle
and cross-checks workflow_dispatch artifact names. Does **not** run hosted
CI — ``gate_d_complete`` / ``gate_f_complete`` stay False.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "ci_artifact_upload_rehearsal_drill.json"

DEVICE_FILES = (
    "android_appium_product_matrix_drill.json",
    "android_emulator_smoke_api24_drill.json",
    "multi_api_android_matrix_drill.json",
    "device_artifact_manifest_drill.json",
    "android_appium_ci_contract.json",
    "multi_device_ci_contract.json",
)
BROWSER_FILES = (
    "multi_browser_portfolio_suite_drill.json",
    "portfolio_artifact_manifest_drill.json",
    "multi_browser_ci_contract.json",
    "compatibility_portfolio_drill.json",
)


def _stage(names: tuple[str, ...], dest: Path) -> tuple[list[dict], list[str]]:
    ops = ROOT / "docs" / "ops-evidence"
    artifacts: list[dict] = []
    missing: list[str] = []
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = ops / name
        if not src.is_file():
            missing.append(name)
            continue
        target = dest / name
        shutil.copy2(src, target)
        artifacts.append({
            "name": name,
            "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "ci_upload_path": f"docs/ops-evidence/{name}",
        })
    return artifacts, missing


def run_ci_artifact_upload_rehearsal_drill(*, ops_dir: Path | None = None) -> dict:
    from .workflow_dispatch_contract_drill import run_workflow_dispatch_contract_drill

    contracts = run_workflow_dispatch_contract_drill(ops_dir=ops_dir)
    staging_root = (
        (Path(ops_dir) / "ci-upload-rehearsal")
        if ops_dir else (ROOT / "artifacts" / "ops" / "ci-upload-rehearsal")
    )
    if staging_root.exists():
        shutil.rmtree(staging_root)
    device_arts, device_missing = _stage(DEVICE_FILES, staging_root / "android")
    browser_arts, browser_missing = _stage(BROWSER_FILES, staging_root / "browsers")
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "ci_artifact_upload_rehearsal",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_upload_rehearsal",
        "staging_dir": str(
            staging_root.relative_to(ROOT) if ops_dir is None else staging_root
        ),
        "android": {
            "artifacts": device_arts,
            "missing": device_missing,
            "ok": not device_missing,
        },
        "browsers": {
            "artifacts": browser_arts,
            "missing": browser_missing,
            "ok": not browser_missing,
        },
        "workflow_contracts_ok": bool(contracts.get("ok")),
        "ok": (
            not device_missing
            and not browser_missing
            and bool(contracts.get("ok"))
        ),
        "reason": (
            f"Local CI upload rehearsal staged "
            f"{len(device_arts)} android + {len(browser_arts)} browser artifacts; "
            "broad hosted multi-device/browser runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "ci_artifact_upload_rehearsal_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "ci_artifact_upload_rehearsal_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
