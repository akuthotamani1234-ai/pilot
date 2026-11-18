"""Gates D/F: validate workflow_dispatch CI YAML contracts (offline).

Parses Android Appium + multi-browser portfolio workflow files for required
triggers, jobs, and artifact paths. Does **not** execute hosted runners —
``gate_d_complete`` / ``gate_f_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "workflow_dispatch_contract_drill.json"

ANDROID = ROOT / ".github" / "workflows" / "android-appium.yml"
BROWSERS = ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml"


def _checks(path: Path, *, need_dispatch: bool, job_hint: str, artifact_hints: list[str]) -> dict:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    present = {
        "file_exists": path.is_file(),
        "workflow_dispatch": "workflow_dispatch" in text,
        "job_hint": job_hint in text,
        "upload_artifact": "upload-artifact" in text,
        "artifacts": {name: name in text for name in artifact_hints},
    }
    ok = (
        present["file_exists"]
        and (not need_dispatch or present["workflow_dispatch"])
        and present["job_hint"]
        and present["upload_artifact"]
        and all(present["artifacts"].values())
    )
    return {"path": str(path.relative_to(ROOT)), "ok": ok, "checks": present}


def run_workflow_dispatch_contract_drill(*, ops_dir: Path | None = None) -> dict:
    android = _checks(
        ANDROID,
        need_dispatch=True,
        job_hint="appium-matrix",
        artifact_hints=[
            "android_appium_ci_contract.json",
            "android_appium_product_matrix_drill.json",
            "device_artifact_manifest_drill.json",
        ],
    )
    browsers = _checks(
        BROWSERS,
        need_dispatch=True,
        job_hint="portfolios",
        artifact_hints=[
            "multi_browser_portfolio_suite_drill.json",
            "portfolio_artifact_manifest_drill.json",
        ],
    )
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "workflow_dispatch_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "android_appium": android,
        "multi_browser": browsers,
        "ok": bool(android.get("ok") and browsers.get("ok")),
        "reason": (
            "workflow_dispatch contracts validated for Appium + multi-browser; "
            "broad hosted runner execution still open"
            if android.get("ok") and browsers.get("ok")
            else "workflow_dispatch contract gaps remain; hosted runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "workflow_dispatch_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "workflow_dispatch_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
