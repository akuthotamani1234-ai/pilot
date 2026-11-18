"""Gate I: API versioning contract evidence (legacy + unsupported rejection).

Records that /api maps to v1 and unsupported versions are rejected. Live hosted
SSO / dashboard still open — gate_i_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .api_versioning import SUPPORTED, resolve_path, versioned_path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "api_version_contract.json"


def build_api_version_contract() -> dict:
    legacy = resolve_path("/api/blueprint/progress")
    v1 = resolve_path("/api/v1/blueprint/progress")
    bad = resolve_path("/api/v99/blueprint/progress")
    try:
        versioned_path("/blueprint/progress", version=1)
        bad_build = None
    except ValueError as exc:
        bad_build = str(exc)
    try:
        versioned_path("/blueprint/progress", version=99)
        unsupported_build_ok = True
        unsupported_build_err = ""
    except ValueError as exc:
        unsupported_build_ok = False
        unsupported_build_err = str(exc)
    checks = [
        {"id": "legacy_maps_v1", "ok": bool(legacy.get("ok") and legacy.get("legacy") and legacy.get("version") == 1)},
        {"id": "v1_canonical", "ok": bool(v1.get("ok") and not v1.get("legacy") and v1.get("version") == 1)},
        {"id": "unsupported_rejected", "ok": bool(not bad.get("ok") and bad.get("version") == 99)},
        {"id": "builder_rejects_unsupported", "ok": unsupported_build_ok is False and "unsupported" in unsupported_build_err.lower()},
    ]
    return {
        "gate_i_complete": False,
        "drill": "api_version_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "supported": sorted(SUPPORTED),
        "legacy": legacy,
        "v1": v1,
        "unsupported": bad,
        "builder_error": bad_build or unsupported_build_err,
        "checks": checks,
        "ok": all(c["ok"] for c in checks),
        "reason": (
            "API versioning contract verified offline (legacy→v1, unsupported rejected); "
            "live hosted SSO / enterprise dashboard still open"
        ),
    }


def run_api_version_drill(*, ops_dir: Path | None = None) -> dict:
    evidence = build_api_version_contract()
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "api_version_contract.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "api_version_contract.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
