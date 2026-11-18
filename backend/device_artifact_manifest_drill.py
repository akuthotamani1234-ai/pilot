"""Gate D: multi-device Appium artifact manifest for hosted CI upload shape.

Hashes Android matrix / Appium evidence into a CI-upload-shaped manifest.
Does **not** run broad multi-device hosted runners — ``gate_d_complete`` stays
False.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "device_artifact_manifest_drill.json"

REQUIRED = (
    "android_appium_product_matrix_drill.json",
    "android_emulator_smoke_drill.json",
    "multi_api_android_matrix_drill.json",
    "device_matrix_drill.json",
    "cross_platform_journey_drill.json",
    "multi_device_ci_contract.json",
    "android_appium_ci_contract.json",
)


def run_device_artifact_manifest_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    artifacts: list[dict] = []
    missing: list[str] = []
    for name in REQUIRED:
        path = ops / name
        if not path.is_file():
            missing.append(name)
            continue
        artifacts.append({
            "name": name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "ci_upload_path": f"docs/ops-evidence/{name}",
        })
    evidence = {
        "gate_d_complete": False,
        "drill": "device_artifact_manifest",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "manifest_only",
        "required": list(REQUIRED),
        "artifacts": artifacts,
        "missing": missing,
        "api_levels": [24, 30, 34],
        "workflow": ".github/workflows/android-appium.yml",
        "workflow_exists": (ROOT / ".github/workflows/android-appium.yml").is_file(),
        "ok": not missing and (
            ROOT / ".github/workflows/android-appium.yml"
        ).is_file(),
        "reason": (
            f"Device/Appium artifact manifest {len(artifacts)}/{len(REQUIRED)} "
            "hashed for CI upload shape; broad multi-device CI runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "device_artifact_manifest_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "device_artifact_manifest_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
