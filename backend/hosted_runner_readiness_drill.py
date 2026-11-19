"""Gates D/F: hosted multi-device/browser runner readiness scores (not executed).

Scores local Appium/portfolio contracts + manifests + upload rehearsal.
Does **not** boot hosted runners — ``gate_d_complete`` / ``gate_f_complete``
stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_runner_readiness_drill.json"

DEVICE_CHECKS = (
    ("android_appium_product_matrix_drill.json", "Appium product matrix"),
    ("android_emulator_smoke_api24_drill.json", "Dedicated API24 smoke"),
    ("multi_api_android_matrix_drill.json", "Multi-API Android matrix"),
    ("device_artifact_manifest_drill.json", "Device artifact manifest"),
    ("multi_device_ci_contract.json", "Multi-device CI contract"),
    ("workflow_dispatch_contract_drill.json", "workflow_dispatch contracts"),
    ("hosted_ci_runner_matrix_drill.json", "Hosted CI runner matrix"),
    ("ci_artifact_upload_rehearsal_drill.json", "CI upload rehearsal"),
    ("android_device_ci_readiness_pack_drill.json", "Android device CI readiness pack"),
    ("hosted_workflow_runner_audit_drill.json", "Hosted workflow runner audit"),
    ("hosted_ci_artifact_retention_contract_drill.json", "Artifact retention contract"),
    ("hosted_ci_permissions_contract_drill.json", "CI permissions contract"),
    ("hosted_ci_timeout_budget_drill.json", "CI timeout budget contract"),
    ("hosted_ci_concurrency_contract_drill.json", "CI concurrency contract"),
    ("hosted_runner_os_matrix_contract_drill.json", "Runner OS matrix contract"),
    ("hosted_ci_cache_key_contract_drill.json", "CI cache-key contract"),
)

BROWSER_CHECKS = (
    ("multi_browser_portfolio_suite_drill.json", "Live 3-engine portfolio suite"),
    ("portfolio_artifact_manifest_drill.json", "Portfolio artifact manifest"),
    ("multi_browser_ci_contract.json", "Multi-browser CI contract"),
    ("workflow_dispatch_contract_drill.json", "workflow_dispatch contracts"),
    ("hosted_ci_runner_matrix_drill.json", "Hosted CI runner matrix"),
    ("ci_artifact_upload_rehearsal_drill.json", "CI upload rehearsal"),
    ("browser_portfolio_ci_readiness_pack_drill.json", "Browser portfolio CI readiness pack"),
    ("hosted_workflow_runner_audit_drill.json", "Hosted workflow runner audit"),
    ("hosted_ci_artifact_retention_contract_drill.json", "Artifact retention contract"),
    ("hosted_ci_permissions_contract_drill.json", "CI permissions contract"),
    ("hosted_ci_timeout_budget_drill.json", "CI timeout budget contract"),
    ("hosted_ci_concurrency_contract_drill.json", "CI concurrency contract"),
    ("hosted_runner_os_matrix_contract_drill.json", "Runner OS matrix contract"),
    ("hosted_ci_cache_key_contract_drill.json", "CI cache-key contract"),
)


def _linked_runner() -> dict:
    return {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "ok": False,
        "drill": "hosted_runner_readiness",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def _score(checks: tuple[tuple[str, str], ...]) -> tuple[list[dict], int]:
    from .finalization import folder_is_linked

    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for name, label in checks:
        path = ops / name
        ready = (not folder_is_linked(path)) and path.is_file()
        rows.append({"artifact": name, "label": label, "ready": ready})
    return rows, sum(1 for row in rows if row["ready"])


def run_hosted_runner_readiness_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "hosted_runner_readiness_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_runner()

    device_rows, device_score = _score(DEVICE_CHECKS)
    browser_rows, browser_score = _score(BROWSER_CHECKS)
    evidence = {
        "gate_d_complete": False,
        "gate_f_complete": False,
        "drill": "hosted_runner_readiness",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "readiness_score_only",
        "multi_device": {
            "score": device_score,
            "score_of": len(DEVICE_CHECKS),
            "checks": device_rows,
            "live_hosted_runners": False,
        },
        "multi_browser": {
            "score": browser_score,
            "score_of": len(BROWSER_CHECKS),
            "checks": browser_rows,
            "live_hosted_runners": False,
        },
        "ok": (
            device_score == len(DEVICE_CHECKS)
            and browser_score == len(BROWSER_CHECKS)
        ),
        "reason": (
            f"Hosted runner readiness device {device_score}/{len(DEVICE_CHECKS)} "
            f"+ browser {browser_score}/{len(BROWSER_CHECKS)}; "
            "broad hosted CI runner execution still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_runner()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_runner()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
