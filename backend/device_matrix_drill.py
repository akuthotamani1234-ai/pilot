"""Gate D: combined device/viewport matrix evidence snapshot.

Merges web viewport evidence (if present), Android protocol dry-run rows, and
the local ADB probe. Live emulator/API24+ still required — gate_d_complete False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .android_adb_probe import run_adb_probe
from .device_matrix import evaluate_matrix, protocol_dry_run_evidence

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "device_matrix_drill.json"


def run_device_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    web_rows = []
    # Prefer last AdminPortal/DemoStore discovery evidence if present in artifacts.
    for name in ("device_matrix_evidence.json",):
        for root in (ROOT / "artifacts" / "ops", ROOT / "docs" / "ops-evidence"):
            path = root / name
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(payload, list):
                        web_rows.extend(payload)
                    elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
                        web_rows.extend(payload["rows"])
                except (OSError, ValueError):
                    pass
    android_dry = protocol_dry_run_evidence()
    adb = run_adb_probe()
    scored = evaluate_matrix(list(web_rows) + list(android_dry))
    evidence = {
        "gate_d_complete": False,
        "drill": "combined_device_matrix_snapshot",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "web_rows": len(web_rows),
        "android_dry_run_rows": len(android_dry),
        "adb_probe": {
            "ok": adb.get("ok"),
            "adb_present": adb.get("adb_present"),
            "devices_online": adb.get("devices_online"),
            "reason": adb.get("reason"),
        },
        "matrix": scored,
        "ok": True,
        "reason": (
            "Combined web + Android protocol dry-run + ADB probe snapshot recorded; "
            "live emulator/API24+ executed matrix still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "device_matrix_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "device_matrix_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
