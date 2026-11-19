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


def _linked_manifest() -> dict:
    return {
        "gate_f_complete": False,
        "ok": False,
        "drill": "portfolio_artifact_manifest",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_portfolio_artifact_manifest_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    out_name = "portfolio_artifact_manifest_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_manifest()
    ops = ROOT / "docs" / "ops-evidence"
    if folder_is_linked(ops):
        return _linked_manifest()
    artifacts: list[dict] = []
    missing: list[str] = []
    for name in REQUIRED:
        path = ops / name
        if folder_is_linked(path) or not path.is_file():
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
            not folder_is_linked(ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml")
            and (ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml").is_file()
        ),
        "ok": not missing and (
            not folder_is_linked(ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml")
            and (ROOT / ".github" / "workflows" / "multi-browser-portfolios.yml").is_file()
        ),
        "reason": (
            f"Portfolio artifact manifest {len(artifacts)}/{len(REQUIRED)} "
            "hashed for CI upload shape; broad hosted multi-browser runner "
            "matrix still open"
        ),
    }
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_manifest()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, json.dumps(evidence, indent=2)):
        return _linked_manifest()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "portfolio_artifact_manifest_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
