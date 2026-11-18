"""Gate F: portfolio artifact manifest for hosted CI upload shape.

Hashes DemoStore portfolio evidence files into a CI-upload-shaped manifest.
Does **not** run hosted multi-browser runners — ``gate_f_complete`` stays False.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "portfolio_artifact_manifest_drill.json"

REQUIRED = (
    "multi_browser_portfolio_suite_drill.json",
    "compatibility_portfolio_drill.json",
    "a11y_portfolio_drill.json",
    "locale_portfolio_drill.json",
    "security_portfolio_drill.json",
    "perf_portfolio_drill.json",
    "visual_portfolio_drill.json",
    "multi_browser_ci_contract.json",
)


def run_portfolio_artifact_manifest_drill(*, ops_dir: Path | None = None) -> dict:
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
        "gate_f_complete": False,
        "drill": "portfolio_artifact_manifest",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "manifest_only",
        "required": list(REQUIRED),
        "artifacts": artifacts,
        "missing": missing,
        "browsers": ["chromium", "firefox", "webkit"],
        "workflow": ".github/workflows/multi-browser-portfolios.yml",
        "workflow_exists": (
            ROOT / ".github/workflows/multi-browser-portfolios.yml"
        ).is_file(),
        "ok": not missing and (
            ROOT / ".github/workflows/multi-browser-portfolios.yml"
        ).is_file(),
        "reason": (
            f"Portfolio artifact manifest {len(artifacts)}/{len(REQUIRED)} "
            "hashed for CI upload shape; broad hosted multi-browser runner "
            "matrix still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "portfolio_artifact_manifest_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "portfolio_artifact_manifest_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
